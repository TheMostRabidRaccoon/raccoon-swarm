"""Semantic search over the swarm filestore — written for readability.

# Why this exists

`filestore_search` does substring matching. If a model searches for
"calibration loop" but the actual file says "Layer 5.5 self-correcting
feedback closure," it misses. Semantic search closes that gap by
comparing *meanings* (via embedding vectors), not characters.

# Why we did NOT use Chroma / Pinecone / Weaviate

Vector DBs are real and useful — at scale. Your filestore is a few
megabytes. A real vector DB would:
  - Add 100MB+ of dependencies.
  - Hide the math behind an API surface.
  - Be slower to start (server process, schema migrations).

For your scale, you can hold every embedding in memory (5000 chunks ×
1536 dims × 4 bytes = ~30MB) and brute-force cosine similarity in
<10ms with numpy. So this module is ~250 lines, no new heavy deps,
and reads top-to-bottom as a teaching artifact for what a vector DB
*actually does* under the hood.

If/when this stops scaling (>50K chunks, sub-second latency required,
multiple servers reading the same index, on-disk-only because RAM is
tight), the swap is mechanical: replace `_search_index` with a Chroma
PersistentClient call. The interface here mimics Chroma's on purpose.

# What it does, end-to-end

  1. Walk the filestore, read every text file (.md / .txt / .json /
     .py / .log).
  2. Chunk each file into ~500-token windows with 100-token overlap so
     a query that straddles a boundary still finds something.
  3. For each chunk, call OpenAI's text-embedding-3-small to get a
     1536-dim vector that represents its *meaning*.
  4. Store {path, chunk_text, embedding, content_hash} in a JSON index.
  5. To search: embed the query, compute cosine similarity against
     every chunk, return top-k.

# Why text-embedding-3-small (not large, not Voyage)

  - You already have OPENAI_API_KEY wired.
  - 5× cheaper than -large, ~95% of the quality at filestore scale.
  - Voyage AI is what Anthropic recommends for production retrieval,
    but adding another API key for marginal gain isn't worth it for
    a few MB of corpus. Swap by replacing one function if you want.

# Cost ceiling

  - text-embedding-3-small: $0.02 per 1M tokens.
  - Your full filestore is probably ~2-3M tokens of text.
  - Initial index build: ~$0.05. Re-embedding only changed files
    (we hash content) keeps incremental cost negligible.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import swarm_filestore

logger = logging.getLogger("SwarmVault")

# ============================================================
# Tunables
# ============================================================

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIMS = 1536  # text-embedding-3-small native dim
CHUNK_CHARS = 2000          # ~500 tokens at ~4 chars/token, OpenAI-ish
CHUNK_OVERLAP_CHARS = 400   # 20% overlap so cross-chunk queries still hit
INDEXABLE_EXTS = {".md", ".txt", ".json", ".py", ".log", ".yaml", ".yml"}
MAX_FILE_BYTES = 1_000_000  # skip files >1MB; embedding token limits are real
INDEX_DIR_NAME = "_semantic_index"
INDEX_FILE_NAME = "index.json"

# Bumped to 2 when per-chunk `meta` (parsed frontmatter) was added. Old v1
# indexes still load fine — chunks simply have no meta until the next reindex,
# and search() treats a missing meta as an empty dict.
INDEX_VERSION = 2

# Hybrid search: how much a keyword (substring) match nudges a chunk's score
# above its raw cosine. Small on purpose — vectors lead, keywords rescue the
# cases where wording matches but the meaning-embedding drifted.
HYBRID_KEYWORD_WEIGHT = 0.2

# Fallback map so `type` filtering works even for files without a `type:` in
# their frontmatter — the filestore's top-level dir already encodes the type.
_DIR_TO_TYPE = {
    "positions": "position", "questions": "question", "pursuits": "pursuit",
    "tasks": "task", "frameworks": "framework", "artifacts": "artifact",
    "logs": "log",
}

_lock = threading.Lock()

# ------------------------------------------------------------------
# In-process search cache. search() used to call _load_index() every
# time, re-reading and JSON-parsing the ENTIRE index (chunk text + all
# 1536-float embeddings) off disk per query — that reparse, not the
# cosine matmul, is what actually gets slow as the corpus grows. We
# cache the parsed chunks + a prebuilt (N, D) numpy matrix and its row
# norms, keyed on the index file's (mtime_ns, size). A writer in any
# process bumps mtime, so cross-process invalidation stays correct.
#
# EXIT RAMP (when this cache stops being the right answer and a real
# vector store earns its keep): ~1e5-1e6 chunks where even a cached
# matmul hurts, OR the day the swarm runs MULTIPLE reader processes
# against one index — whichever lands first. In the multi-process case
# the cache is no longer free: each process holds its own copy of the
# matrix in RAM and re-parses on every mtime change. That's an
# architecture decision away, not a corpus-growth away. At that point
# the swap to Chroma/LanceDB is the mechanical one the module header
# already describes.
_cache_lock = threading.Lock()
_SEARCH_CACHE: dict = {"key": None, "chunks": [], "matrix": None, "dnorms": None}


# ============================================================
# Storage paths
# ============================================================

def _index_dir() -> Path:
    """The semantic index lives at <storage>/swarm/_semantic_index/.
    The leading underscore keeps it out of the swarm's normal
    artifact/positions/etc. tree (which validates kebab-case names
    starting with a letter)."""
    p = swarm_filestore._storage_root() / INDEX_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def _index_path() -> Path:
    return _index_dir() / INDEX_FILE_NAME


# ============================================================
# Chunking
# ============================================================

def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping windows.

    Why overlap? If the query asks 'who maintains the calibration loop'
    and the answer spans 'maintains' (end of chunk N) and 'calibration
    loop' (start of chunk N+1), neither chunk wins on its own. Overlap
    means at least one chunk contains the full phrase.

    Why character-count instead of token-count? Approximation. Real
    tokenization (tiktoken) is a few percent more accurate but adds
    a dep. At our scale, char-count windows are fine.
    """
    if not text:
        return []
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks = []
    start = 0
    step = CHUNK_CHARS - CHUNK_OVERLAP_CHARS
    while start < len(text):
        chunks.append(text[start:start + CHUNK_CHARS])
        start += step
    return chunks


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# ============================================================
# Embedding (OpenAI)
# ============================================================

def _openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set — needed for semantic search embeddings")
    import openai
    return openai.OpenAI(api_key=api_key)


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Call OpenAI's embeddings API on a batch.

    Why batch? The API accepts up to 2048 inputs per request and you
    pay per-token, not per-request. Batching cuts wall time dramatically
    on initial index build (one HTTP round-trip per ~100 chunks instead
    of one per chunk).
    """
    if not texts:
        return []
    client = _openai_client()
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def _embed_one(text: str) -> list[float]:
    return _embed_batch([text])[0]


# ============================================================
# Frontmatter / metadata
# ============================================================

_FM_FENCE_RE = re.compile(r"^﻿?---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    """Parse a leading YAML-ish `--- ... ---` frontmatter block.

    Deliberately tiny and stdlib-only (no PyYAML dep — keeping the
    dependency surface small is the whole point of this layer). Handles:
      key: value
      key: [a, b, c]          # inline list
      key:                    # block list
        - a
        - b
    Keys are lowercased; quotes stripped; unknown/garbage lines skipped.
    Returns {} when there's no frontmatter.
    """
    if not text:
        return {}
    m = _FM_FENCE_RE.match(text)
    if not m:
        return {}
    body = m.group(1)
    meta: dict = {}
    pending_key: str | None = None
    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        # Block-list continuation line ("  - item") for the previous key.
        stripped = line.strip()
        if stripped.startswith("- ") and pending_key:
            meta.setdefault(pending_key, [])
            if isinstance(meta[pending_key], list):
                meta[pending_key].append(_strip_scalar(stripped[2:]))
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if not key:
            continue
        if val == "":
            # Either a block list follows, or an empty value.
            meta[key] = []
            pending_key = key
            continue
        pending_key = None
        if val.startswith("[") and val.endswith("]"):
            items = [_strip_scalar(x) for x in val[1:-1].split(",")]
            meta[key] = [x for x in items if x]
        else:
            meta[key] = _strip_scalar(val)
    # Drop keys left as empty lists with no items (bare "key:" and nothing).
    return {k: v for k, v in meta.items() if v != []}


def _strip_scalar(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    return s.strip()


def _derive_meta(rel_path: str, text: str) -> dict:
    """Build the per-chunk metadata dict from a file's path + frontmatter.

    Always includes `dir` (top-level filestore directory) and a `type`
    (explicit frontmatter `type:` wins; otherwise derived from `dir`).
    Tags are normalized to a lowercased list.
    """
    meta = _parse_frontmatter(text)
    top = rel_path.replace("\\", "/").split("/")[0] if rel_path else ""
    meta.setdefault("dir", top)
    if "type" not in meta and top in _DIR_TO_TYPE:
        meta["type"] = _DIR_TO_TYPE[top]
    # Normalize tags to a lowercased list regardless of how they were written.
    tags = meta.get("tags", meta.get("tag"))
    if tags is not None:
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        meta["tags"] = [str(t).lower() for t in tags]
        meta.pop("tag", None)
    return meta


def _meta_date(meta: dict) -> str | None:
    """The most relevant date on a chunk's meta, for after/before filtering."""
    for k in ("date", "updated", "created"):
        v = meta.get(k)
        if v:
            return str(v)
    return None


def _chunk_matches_filters(meta: dict, filters: dict | None) -> bool:
    """AND-match a chunk's meta against a filter dict. Empty filters -> True.

    Supported keys:
      after / before  -> lexicographic ISO-date compare on the chunk's date
      tag / tags       -> every requested tag must be present (case-insensitive)
      anything else    -> case-insensitive exact match on meta[key]
    A chunk missing the field a filter needs does NOT match (fail-closed).
    """
    if not filters:
        return True
    meta = meta or {}
    for key, want in filters.items():
        k = key.lower()
        if k in ("after", "before"):
            d = _meta_date(meta)
            if d is None:
                return False
            if k == "after" and not (d >= str(want)):
                return False
            if k == "before" and not (d <= str(want)):
                return False
        elif k in ("tag", "tags"):
            have = {str(t).lower() for t in (meta.get("tags") or [])}
            wants = want if isinstance(want, (list, tuple, set)) else [want]
            if not all(str(w).lower() in have for w in wants):
                return False
        else:
            got = meta.get(k)
            if got is None or str(got).lower() != str(want).lower():
                return False
    return True


def _keyword_frac(query: str, text: str) -> float:
    """Fraction of the query's word-tokens that appear (substring) in text.

    The keyword half of hybrid search — cheap, case-insensitive, no index.
    """
    terms = [t for t in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(t) > 1]
    if not terms:
        return 0.0
    low = (text or "").lower()
    hits = sum(1 for t in set(terms) if t in low)
    return hits / len(set(terms))


# ============================================================
# Cosine similarity (the whole vector DB, basically)
# ============================================================

def _cosine_similarity(query_vec: list[float], doc_vecs: "list[list[float]] | object") -> "object":
    """Return cosine similarity between query and each doc vector.

    Cosine similarity = dot(a, b) / (||a|| * ||b||). Range: -1 to 1.
    Same direction → 1, orthogonal → 0, opposite → -1. For text
    embeddings on similar content, scores typically cluster 0.3-0.9.

    Why cosine and not Euclidean? Embedding vectors are commonly
    L2-normalized so magnitude carries no information; cosine
    captures only direction (which IS the meaning).

    We use numpy because it's fast (vectorized over thousands of docs
    in microseconds) and already a swarm dep. The matrix form below
    computes the entire similarity vector in one operation.
    """
    import numpy as np
    q = np.asarray(query_vec, dtype=np.float32)
    d = np.asarray(doc_vecs, dtype=np.float32)  # shape: (N, EMBED_DIMS)
    q_norm = np.linalg.norm(q)
    d_norms = np.linalg.norm(d, axis=1)
    # Avoid division by zero on accidentally-zero vectors
    denom = (d_norms * q_norm).clip(min=1e-12)
    return (d @ q) / denom


# ============================================================
# Index format
# ============================================================
#
# index.json shape:
# {
#   "version": 1,
#   "model": "text-embedding-3-small",
#   "built_at": "2026-05-09T...",
#   "files": {
#     "<rel-path>": {"content_hash": "...", "chunk_count": 7}
#   },
#   "chunks": [
#     {"path": "...", "chunk_index": 0, "text": "...",
#      "embedding": [0.01, -0.02, ...], "content_hash": "..."},
#     ...
#   ]
# }
# ============================================================

def _load_index() -> dict:
    p = _index_path()
    if not p.exists():
        return {"version": 1, "model": EMBED_MODEL, "files": {}, "chunks": []}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"semantic index unreadable, starting fresh: {e}")
        return {"version": 1, "model": EMBED_MODEL, "files": {}, "chunks": []}


def _save_index(index: dict) -> None:
    p = _index_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, default=str))
    os.replace(tmp, p)


# ============================================================
# Indexing
# ============================================================

def _walk_filestore() -> Iterable[Path]:
    """Yield every indexable file under the filestore root.

    Skips the index directory itself, hidden dirs, and files outside
    INDEXABLE_EXTS or larger than MAX_FILE_BYTES.
    """
    root = swarm_filestore._storage_root()
    if not root.exists():
        return
    skip_dirs = {INDEX_DIR_NAME, ".git", ".venv", "__pycache__"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs or part.startswith(".") for part in path.parts):
            continue
        if path.suffix.lower() not in INDEXABLE_EXTS:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def reindex(force: bool = False) -> dict:
    """(Re)build the semantic index from the current filestore.

    Idempotent: only re-embeds files whose content_hash has changed
    since last build (so a small edit doesn't rebuild the whole index).
    Pass force=True to re-embed everything regardless.

    Returns a summary dict for logging.
    """
    started = time.monotonic()
    index = _load_index()
    if index.get("model") != EMBED_MODEL or force:
        # Model changed → start over (mixing dim sizes breaks similarity).
        index = {"version": 1, "model": EMBED_MODEL, "files": {}, "chunks": []}

    existing_files: dict = index.get("files", {})
    keep_chunks = list(index.get("chunks", []))
    files_seen: set[str] = set()

    new_chunks_to_embed: list[dict] = []  # rows pending embedding
    embedded = skipped = 0

    root = swarm_filestore._storage_root()
    for fp in _walk_filestore():
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning(f"semantic reindex: skip {fp} ({e})")
            continue
        rel = str(fp.relative_to(root))
        files_seen.add(rel)
        h = _content_hash(text)

        prior = existing_files.get(rel)
        if prior and prior.get("content_hash") == h and not force:
            skipped += 1
            continue

        # Drop any prior chunks for this file before re-embedding
        keep_chunks = [c for c in keep_chunks if c.get("path") != rel]

        for i, chunk in enumerate(_chunk_text(text)):
            new_chunks_to_embed.append({
                "path": rel, "chunk_index": i, "text": chunk, "content_hash": h,
            })
        existing_files[rel] = {
            "content_hash": h,
            "chunk_count": len(_chunk_text(text)),
        }
        embedded += 1

    # Drop files that no longer exist
    removed = [rel for rel in list(existing_files.keys()) if rel not in files_seen]
    for rel in removed:
        existing_files.pop(rel, None)
        keep_chunks = [c for c in keep_chunks if c.get("path") != rel]

    # Embed new/changed chunks in batches of 100
    if new_chunks_to_embed:
        batch_size = 100
        for start in range(0, len(new_chunks_to_embed), batch_size):
            batch = new_chunks_to_embed[start:start + batch_size]
            embeddings = _embed_batch([row["text"] for row in batch])
            for row, vec in zip(batch, embeddings):
                row["embedding"] = vec
                keep_chunks.append(row)

    # Metadata enrichment pass (API-free): attach parsed-frontmatter `meta`
    # to every chunk. Decoupled from embedding so unchanged files still get
    # fresh metadata each reindex without re-embedding. One read per distinct
    # path, not per chunk.
    meta_by_path: dict = {}
    for c in keep_chunks:
        rel = c.get("path")
        if rel not in meta_by_path:
            fp = root / rel
            try:
                ftext = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                ftext = ""
            meta_by_path[rel] = _derive_meta(rel, ftext)
        c["meta"] = meta_by_path[rel]

    index["files"] = existing_files
    index["chunks"] = keep_chunks
    index["model"] = EMBED_MODEL
    index["version"] = INDEX_VERSION
    index["built_at"] = datetime.now().isoformat(timespec="seconds")

    with _lock:
        _save_index(index)
    # New index on disk → drop the in-process search cache so the next query
    # rebuilds from fresh content (the mtime key would catch this too; this is
    # just immediate and explicit).
    _invalidate_search_cache()

    elapsed = round(time.monotonic() - started, 1)
    summary = {
        "ok": True,
        "files_embedded_or_changed": embedded,
        "files_unchanged": skipped,
        "files_removed": len(removed),
        "chunks_added": len(new_chunks_to_embed),
        "total_chunks": len(keep_chunks),
        "total_files": len(existing_files),
        "elapsed_s": elapsed,
        "model": EMBED_MODEL,
    }
    logger.info(f"swarm_semantic reindex: {summary}")
    return summary


# ============================================================
# Search cache
# ============================================================

def _index_file_key():
    """Cache key = (mtime_ns, size) of the index file, or None if absent.

    Any writer (this or another process) bumps mtime, so comparing this key
    is a correct cross-process staleness check without holding the file open.
    """
    p = _index_path()
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _get_search_cache() -> dict:
    """Return {chunks, matrix, dnorms} for the current index, rebuilding the
    parsed chunks + numpy matrix only when the index file changes.

    This is the fix for the per-query full-index reparse: on a cache hit we do
    zero disk I/O and zero JSON parsing — just an in-memory matmul in search().
    """
    key = _index_file_key()
    with _cache_lock:
        if key is not None and _SEARCH_CACHE["key"] == key:
            return _SEARCH_CACHE
        index = _load_index()
        chunks = index.get("chunks") or []
        matrix = dnorms = None
        if chunks:
            import numpy as np
            matrix = np.asarray([c["embedding"] for c in chunks], dtype=np.float32)
            dnorms = np.linalg.norm(matrix, axis=1).clip(min=1e-12)
        _SEARCH_CACHE.update(key=key, chunks=chunks, matrix=matrix, dnorms=dnorms)
        return _SEARCH_CACHE


def _invalidate_search_cache() -> None:
    with _cache_lock:
        _SEARCH_CACHE.update(key=None, chunks=[], matrix=None, dnorms=None)


# ============================================================
# Search
# ============================================================

def search(query: str, top_k: int = 5, min_score: float = 0.0,
           filters: dict | None = None, hybrid: bool = False) -> dict:
    """Run a semantic search. Embeds the query, scores it against the indexed
    chunks, returns the top_k highest-scoring.

    Args:
      filters: optional metadata narrowing, matched against each chunk's parsed
               frontmatter (AND across keys). E.g.
               {"model": "claude", "type": "position", "tag": "governance",
                "after": "2026-05"}. Chunks are filtered BEFORE scoring, so a
               tight filter also makes the search cheaper.
      hybrid:  when True, blend a cheap keyword (substring) signal into the
               score so chunks whose wording matches the query surface even if
               their embedding drifted. Vectors still lead (see
               HYBRID_KEYWORD_WEIGHT).

    Returns {ok, query, results: [{path, chunk_index, snippet, score, meta}]}.
    Snippet is the first ~300 chars so the model gets context without flooding
    the prompt.
    """
    if not query or len(query.strip()) < 2:
        return {"ok": False, "error": "query too short"}

    cache = _get_search_cache()
    chunks = cache["chunks"]
    if not chunks:
        return {"ok": False, "error": "index is empty — run reindex() or POST /semantic/reindex"}

    # Metadata pre-filter: restrict to candidate chunk indices before we spend
    # an embedding call or touch the matrix.
    if filters:
        candidates = [i for i, c in enumerate(chunks)
                      if _chunk_matches_filters(c.get("meta"), filters)]
        if not candidates:
            return {"ok": True, "query": query, "results": [], "total_returned": 0,
                    "index_size_chunks": len(chunks), "filtered_candidates": 0,
                    "model": EMBED_MODEL}
    else:
        candidates = None  # all

    try:
        q_vec = _embed_one(query)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    import numpy as np
    q = np.asarray(q_vec, dtype=np.float32)
    q_norm = float(np.linalg.norm(q)) or 1e-12
    matrix, dnorms = cache["matrix"], cache["dnorms"]

    if candidates is None:
        sims = (matrix @ q) / (dnorms * q_norm)
        idxs = np.arange(len(chunks))
    else:
        sub = matrix[candidates]
        sub_norms = dnorms[candidates]
        sims = (sub @ q) / (sub_norms * q_norm)
        idxs = np.asarray(candidates)

    scores = sims.astype(float)
    if hybrid:
        # Blend in the keyword fraction per candidate chunk.
        bonus = np.asarray(
            [_keyword_frac(query, chunks[int(i)]["text"]) for i in idxs],
            dtype=np.float64,
        )
        scores = scores + HYBRID_KEYWORD_WEIGHT * bonus

    order = np.argsort(-scores)[:max(1, top_k)]
    results = []
    for rank, pos in enumerate(order):
        score = float(scores[int(pos)])
        if score < min_score:
            break
        c = chunks[int(idxs[int(pos)])]
        snippet = c["text"][:300].replace("\n", " ").strip()
        results.append({
            "rank": rank + 1,
            "path": c["path"],
            "chunk_index": c["chunk_index"],
            "snippet": snippet,
            "score": round(score, 4),
            "meta": c.get("meta", {}),
        })
    out = {
        "ok": True,
        "query": query,
        "results": results,
        "total_returned": len(results),
        "index_size_chunks": len(chunks),
        "model": EMBED_MODEL,
    }
    if filters:
        out["filtered_candidates"] = len(candidates)
    if hybrid:
        out["hybrid"] = True
    return out


def status() -> dict:
    index = _load_index()
    chunks = index.get("chunks") or []
    files = index.get("files") or {}
    p = _index_path()
    size_bytes = p.stat().st_size if p.exists() else 0
    return {
        "model": index.get("model"),
        "built_at": index.get("built_at"),
        "total_files": len(files),
        "total_chunks": len(chunks),
        "index_size_bytes": size_bytes,
        "openai_key_configured": bool(os.getenv("OPENAI_API_KEY")),
        "chunk_chars": CHUNK_CHARS,
        "chunk_overlap_chars": CHUNK_OVERLAP_CHARS,
        "indexable_extensions": sorted(INDEXABLE_EXTS),
    }
