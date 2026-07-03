"""Evidence catalog — the read-only source-of-truth layer (M1a).

The difference between "I remember this" and "I can prove this". The filestore
(swarm_filestore) is the swarm's own memory; the evidence catalog is a separate,
provenance-carrying index of *source* material (allowlisted Drive folders, docs,
etc.) that a claim can cite. A cite is `{source_id, content_hash, chunk_index}`;
if it doesn't resolve, it's a phantom — the same discipline as the filestore's
phantom-write detection, applied to phantom *evidence*.

Design decisions baked in on day one (from the council design review):

- **Origin class is in the schema, not a flag.** Every source is
  conductor-authored / swarm-authored / third-party / unknown. The swarm's own
  syntheses flow into Drive, so a naive index lets it cite itself as independent
  evidence (the "citation-laundering loop"). Origin is what M2's corroboration
  rule keys off — independent corroboration may not be swarm-authored. The data
  is here now even though the *rule* lands with citation-verification.
- **Content-hash dedup.** The real corpus is export sprawl (the same doc as a
  Google Doc + two .txt exports), not elegant revisions. Identical content is
  linked to one canonical source and indexed once, so search never returns the
  same text three times.
- **Read-only.** No promotion into swarm memory here. That flows through the
  human-gated swarm_proposals pattern in a later milestone — "what enters
  permanent memory" gets the same one-gated-step treatment as the tool registry.

Stdlib only (sqlite3 + hashlib). No Drive API in this module — sources are handed
in via `catalog_source`, so it unit-tests with synthetic data and the Drive
ingest (build_source_catalog.py) is a thin separate script.
"""
from __future__ import annotations

import functools
import hashlib
import os
import re
import sqlite3
from datetime import datetime

# Origin classes — the anti-laundering primitive. Corroboration independence
# (M2) keys off these: swarm-authored evidence never independently corroborates
# a swarm claim.
CONDUCTOR = "conductor-authored"
SWARM = "swarm-authored"
THIRD_PARTY = "third-party"
UNKNOWN = "unknown"
ORIGINS = (CONDUCTOR, SWARM, THIRD_PARTY, UNKNOWN)

DEFAULT_CHUNK_CHARS = 800
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


# ============================================================
# Connection + schema
# ============================================================

def _db_path() -> str:
    """Where evidence.db lives. RRI_EVIDENCE_DB wins; else under the storage
    dir (RRI_STORAGE_DIR), else the cwd. Kept independent of swarm_filestore so
    the catalog is its own subsystem."""
    explicit = os.environ.get("RRI_EVIDENCE_DB")
    if explicit:
        return explicit
    base = os.environ.get("RRI_STORAGE_DIR", ".")
    return os.path.join(base, "evidence", "evidence.db")


@functools.lru_cache(maxsize=1)
def _fts5_available() -> bool:
    """Whether this sqlite build has FTS5 compiled in (process-global). If not,
    search falls back to a ranked LIKE scan so the catalog still works."""
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE _t USING fts5(x)")
        c.close()
        return True
    except sqlite3.OperationalError:
        return False


def connect(db_path: "str | None" = None) -> sqlite3.Connection:
    """Open (creating dirs) and ensure the schema. Pass ':memory:' for tests."""
    path = db_path or _db_path()
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sources (
            source_id           INTEGER PRIMARY KEY,
            external_id         TEXT UNIQUE,          -- Drive id / path (nullable)
            title               TEXT NOT NULL,
            mime_type           TEXT,
            origin              TEXT NOT NULL,
            owner               TEXT,
            url                 TEXT,
            modified_time       TEXT,
            content_hash        TEXT NOT NULL,
            canonical_source_id INTEGER,              -- self if canonical; else the dup's canonical
            ingested_at         TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sources_hash ON sources(content_hash);
        CREATE INDEX IF NOT EXISTS idx_sources_canonical ON sources(canonical_source_id);

        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id     INTEGER PRIMARY KEY,
            source_id    INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
            chunk_index  INTEGER NOT NULL,
            heading_path TEXT,
            char_start   INTEGER,
            char_end     INTEGER,
            text         TEXT NOT NULL,
            UNIQUE(source_id, chunk_index)
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
        """
    )
    if _fts5_available():
        # Contentless-style external-content FTS over chunk text, keyed by chunk_id.
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
            "text, chunk_id UNINDEXED, tokenize='porter')"
        )
    conn.commit()


# ============================================================
# Chunking (dependency-free, provenance-carrying)
# ============================================================

def chunk_text(text: str, target_chars: int = DEFAULT_CHUNK_CHARS) -> list[dict]:
    """Split text into ~target_chars chunks on blank-line/heading boundaries,
    tracking the current markdown heading path and character offsets. Returns
    [{chunk_index, heading_path, char_start, char_end, text}].
    """
    if not (text or "").strip():
        return []
    lines = text.splitlines(keepends=True)
    chunks: list[dict] = []
    heading_stack: list[str] = []
    buf: list[str] = []
    buf_start = 0
    pos = 0
    idx = 0

    def _flush(end_pos: int):
        nonlocal idx
        body = "".join(buf).strip()
        if body:
            chunks.append({
                "chunk_index": idx,
                "heading_path": " > ".join(heading_stack) if heading_stack else None,
                "char_start": buf_start,
                "char_end": end_pos,
                "text": body,
            })
            idx += 1

    for line in lines:
        m = _HEADING_RE.match(line.strip("\n"))
        if m:
            # Heading starts a new chunk and updates the heading path (by depth).
            _flush(pos)
            depth = len(m.group(1))
            heading_stack = heading_stack[: depth - 1] + [m.group(2)]
            buf, buf_start = [], pos
        buf.append(line)
        pos += len(line)
        if sum(len(x) for x in buf) >= target_chars and line.strip() == "":
            _flush(pos)
            buf, buf_start = [], pos
    _flush(pos)
    return chunks


def content_hash(text: str) -> str:
    """Dedup key: sha256 of whitespace-normalized text, so a Google Doc and its
    .txt export (same words, different byte layout) hash identically."""
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ============================================================
# Cataloguing (the write path — but write to the catalog, not swarm memory)
# ============================================================

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _index_chunks(conn: sqlite3.Connection, source_id: int, text: str) -> int:
    rows = chunk_text(text)
    for c in rows:
        cur = conn.execute(
            "INSERT INTO chunks(source_id, chunk_index, heading_path, char_start, char_end, text)"
            " VALUES(?,?,?,?,?,?)",
            (source_id, c["chunk_index"], c["heading_path"], c["char_start"], c["char_end"], c["text"]),
        )
        if _fts5_available():
            conn.execute("INSERT INTO chunks_fts(text, chunk_id) VALUES(?,?)", (c["text"], cur.lastrowid))
    return len(rows)


def _drop_chunks(conn: sqlite3.Connection, source_id: int) -> None:
    if _fts5_available():
        conn.execute(
            "DELETE FROM chunks_fts WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE source_id=?)",
            (source_id,),
        )
    conn.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))


def catalog_source(conn: sqlite3.Connection, *, title: str, text: str, origin: str,
                   external_id: "str | None" = None, mime_type: "str | None" = None,
                   owner: "str | None" = None, url: "str | None" = None,
                   modified_time: "str | None" = None) -> dict:
    """Catalog one source (idempotent by external_id, deduped by content).

    Returns {source_id, canonical_source_id, is_duplicate, chunks, status} where
    status is 'created' | 'duplicate' | 'unchanged' | 'updated'.

    - Same external_id, same content  -> unchanged (no-op).
    - Same external_id, new content    -> updated (re-chunked).
    - New content matching an existing canonical -> duplicate (linked, not
      re-indexed; export sprawl collapses to one canonical copy).
    - Otherwise                        -> created as a new canonical source.
    """
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {ORIGINS}, got {origin!r}")
    h = content_hash(text)

    existing = None
    if external_id is not None:
        existing = conn.execute("SELECT * FROM sources WHERE external_id=?", (external_id,)).fetchone()

    if existing is not None:
        if existing["content_hash"] == h:
            return {"source_id": existing["source_id"],
                    "canonical_source_id": existing["canonical_source_id"],
                    "is_duplicate": existing["canonical_source_id"] != existing["source_id"],
                    "chunks": 0, "status": "unchanged"}
        # Content changed — re-catalog in place (M1a keeps no revision history;
        # immutable snapshots are a later milestone).
        sid = existing["source_id"]
        _drop_chunks(conn, sid)
        conn.execute(
            "UPDATE sources SET title=?, mime_type=?, origin=?, owner=?, url=?, modified_time=?,"
            " content_hash=?, canonical_source_id=source_id, ingested_at=? WHERE source_id=?",
            (title, mime_type, origin, owner, url, modified_time, h, _now(), sid),
        )
        n = _index_chunks(conn, sid, text)
        conn.commit()
        return {"source_id": sid, "canonical_source_id": sid, "is_duplicate": False,
                "chunks": n, "status": "updated"}

    # New source. Does its content already exist under a canonical source?
    canon = conn.execute(
        "SELECT source_id FROM sources WHERE content_hash=? AND canonical_source_id=source_id"
        " ORDER BY source_id LIMIT 1", (h,),
    ).fetchone()

    cur = conn.execute(
        "INSERT INTO sources(external_id, title, mime_type, origin, owner, url, modified_time,"
        " content_hash, canonical_source_id, ingested_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (external_id, title, mime_type, origin, owner, url, modified_time, h, None, _now()),
    )
    sid = cur.lastrowid
    if canon is not None:
        # Duplicate content: link to the canonical, do NOT re-index its chunks.
        conn.execute("UPDATE sources SET canonical_source_id=? WHERE source_id=?", (canon["source_id"], sid))
        conn.commit()
        return {"source_id": sid, "canonical_source_id": canon["source_id"],
                "is_duplicate": True, "chunks": 0, "status": "duplicate"}

    conn.execute("UPDATE sources SET canonical_source_id=source_id WHERE source_id=?", (sid,))
    n = _index_chunks(conn, sid, text)
    conn.commit()
    return {"source_id": sid, "canonical_source_id": sid, "is_duplicate": False,
            "chunks": n, "status": "created"}


# ============================================================
# Retrieval (read-only, cited excerpts)
# ============================================================

def _row_to_hit(r: sqlite3.Row, score: float) -> dict:
    return {
        "source_id": r["source_id"],
        "chunk_index": r["chunk_index"],
        "title": r["title"],
        "origin": r["origin"],
        "url": r["url"],
        "heading_path": r["heading_path"],
        "content_hash": r["content_hash"],
        "score": round(score, 4),
        "snippet": _snippet(r["text"]),
    }


def _snippet(text: str, limit: int = 240) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[:limit].rstrip() + "…"


def search(conn: sqlite3.Connection, query: str, k: int = 5,
           origins: "tuple | None" = None) -> list[dict]:
    """Return up to k cited excerpts best-first. Duplicates are never returned
    (only canonical sources carry chunks). `origins` optionally restricts to
    given origin classes. Uses FTS5 when available, else a ranked LIKE scan.
    """
    if not (query or "").strip():
        return []
    origin_filter = ""
    params: list = []
    if origins:
        origin_filter = " AND s.origin IN (%s)" % ",".join("?" * len(origins))

    if _fts5_available():
        sql = (
            "SELECT c.source_id, c.chunk_index, c.heading_path, c.text,"
            " s.title, s.origin, s.url, s.content_hash, bm25(chunks_fts) AS bm"
            " FROM chunks_fts"
            " JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id"
            " JOIN sources s ON s.source_id = c.source_id"
            " WHERE chunks_fts MATCH ?" + origin_filter +
            " ORDER BY bm LIMIT ?"
        )
        params = [_fts_query(query)] + (list(origins) if origins else []) + [k]
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []  # malformed FTS query (e.g. only punctuation)
        # bm25 is ascending (lower = better); flip to a friendly descending score.
        return [_row_to_hit(r, -r["bm"]) for r in rows]

    return _search_like(conn, query, k, origins)


def _fts_query(query: str) -> str:
    """Turn a free-text query into a safe FTS5 MATCH: OR the bare terms so
    punctuation/operators in user text can't become FTS syntax errors."""
    terms = re.findall(r"[A-Za-z0-9]+", query.lower())
    return " OR ".join(terms) if terms else '""'


def _search_like(conn: sqlite3.Connection, query: str, k: int, origins) -> list[dict]:
    """FTS5-free fallback: substring scan, scored like swarm_filestore.search."""
    terms = re.findall(r"[A-Za-z0-9]+", query.lower())
    if not terms:
        return []
    origin_filter = ""
    params: list = []
    if origins:
        origin_filter = " AND s.origin IN (%s)" % ",".join("?" * len(origins))
        params = list(origins)
    rows = conn.execute(
        "SELECT c.source_id, c.chunk_index, c.heading_path, c.text,"
        " s.title, s.origin, s.url, s.content_hash FROM chunks c"
        " JOIN sources s ON s.source_id = c.source_id WHERE 1=1" + origin_filter, params,
    ).fetchall()
    scored = []
    for r in rows:
        low = r["text"].lower()
        score = sum(low.count(t) for t in terms)
        if score:
            scored.append((score, r))
    scored.sort(key=lambda t: (t[0], t[1]["source_id"], -t[1]["chunk_index"]), reverse=True)
    return [_row_to_hit(r, float(s)) for s, r in scored[:k]]


def fetch(conn: sqlite3.Connection, source_id: int, chunk_index: int) -> "dict | None":
    """The bounded excerpt for one chunk anchor, with full provenance. This is
    what a model calls after a search to read (and then cite) a specific
    passage — never the whole doc."""
    r = conn.execute(
        "SELECT c.source_id, c.chunk_index, c.heading_path, c.char_start, c.char_end, c.text,"
        " s.title, s.origin, s.owner, s.url, s.modified_time, s.content_hash"
        " FROM chunks c JOIN sources s ON s.source_id=c.source_id"
        " WHERE c.source_id=? AND c.chunk_index=?", (source_id, chunk_index),
    ).fetchone()
    if r is None:
        return None
    return {
        "source_id": r["source_id"], "chunk_index": r["chunk_index"],
        "title": r["title"], "origin": r["origin"], "owner": r["owner"], "url": r["url"],
        "modified_time": r["modified_time"], "heading_path": r["heading_path"],
        "char_start": r["char_start"], "char_end": r["char_end"],
        "content_hash": r["content_hash"], "text": r["text"],
    }


def resolve_citation(conn: sqlite3.Connection, source_id: int, content_hash: str,
                     chunk_index: int) -> dict:
    """Verify a citation {source_id, content_hash, chunk_index} still resolves.

    Foundation for M2's `citation_gap` (the Closer re-fetches every cite in a
    synthesis; unresolved ones are phantoms — same as phantom writes). Returns
    {ok, reason, excerpt}. `stale` = the source exists but its content changed
    since the citation was made (hash mismatch).
    """
    excerpt = fetch(conn, source_id, chunk_index)
    if excerpt is None:
        return {"ok": False, "reason": "not-found", "excerpt": None}
    if excerpt["content_hash"] != content_hash:
        return {"ok": False, "reason": "stale", "excerpt": excerpt}
    return {"ok": True, "reason": "resolved", "excerpt": excerpt}


def is_independent_corroborator(origin: str) -> bool:
    """M2 anti-laundering primitive: swarm-authored evidence cannot serve as
    independent corroboration of a swarm claim. (The rule that consumes this
    lands with citation-verification; the origin data is already here.)"""
    return origin != SWARM


def stats(conn: sqlite3.Connection) -> dict:
    src = conn.execute("SELECT COUNT(*) n FROM sources").fetchone()["n"]
    dup = conn.execute(
        "SELECT COUNT(*) n FROM sources WHERE canonical_source_id != source_id").fetchone()["n"]
    ch = conn.execute("SELECT COUNT(*) n FROM chunks").fetchone()["n"]
    by_origin = {row["origin"]: row["n"] for row in conn.execute(
        "SELECT origin, COUNT(*) n FROM sources GROUP BY origin")}
    return {"sources": src, "duplicates": dup, "canonical": src - dup,
            "chunks": ch, "by_origin": by_origin, "fts5": _fts5_available()}
