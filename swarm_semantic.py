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

_lock = threading.Lock()


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

    index["files"] = existing_files
    index["chunks"] = keep_chunks
    index["model"] = EMBED_MODEL
    index["built_at"] = datetime.now().isoformat(timespec="seconds")

    with _lock:
        _save_index(index)

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
# Search
# ============================================================

def search(query: str, top_k: int = 5, min_score: float = 0.0) -> dict:
    """Run a semantic search. Embeds the query, scores it against every
    chunk in the index, returns the top_k highest cosines.

    Returns {ok, query, results: [{path, chunk_index, snippet, score}]}.
    Snippet is the first ~300 chars of the chunk so the model gets
    context without flooding the prompt.
    """
    if not query or len(query.strip()) < 2:
        return {"ok": False, "error": "query too short"}

    index = _load_index()
    chunks = index.get("chunks") or []
    if not chunks:
        return {"ok": False, "error": "index is empty — run reindex() or POST /semantic/reindex"}

    try:
        q_vec = _embed_one(query)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    doc_vecs = [c["embedding"] for c in chunks]
    sims = _cosine_similarity(q_vec, doc_vecs)

    # Argsort descending; numpy sorts ascending so we negate.
    import numpy as np
    order = np.argsort(-sims)[:max(1, top_k)]
    results = []
    for rank, idx in enumerate(order):
        score = float(sims[int(idx)])
        if score < min_score:
            break
        c = chunks[int(idx)]
        snippet = c["text"][:300].replace("\n", " ").strip()
        results.append({
            "rank": rank + 1,
            "path": c["path"],
            "chunk_index": c["chunk_index"],
            "snippet": snippet,
            "score": round(score, 4),
        })
    return {
        "ok": True,
        "query": query,
        "results": results,
        "total_returned": len(results),
        "index_size_chunks": len(chunks),
        "model": index.get("model", EMBED_MODEL),
    }


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
