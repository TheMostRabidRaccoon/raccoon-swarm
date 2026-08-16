"""Recall orchestration over the durable filestore + semantic index.

`swarm_semantic` is a good vector engine, but historically it indexed raw disk and
required an explicit rebuild. This layer supplies two memory invariants:

1. VISIBILITY PARITY — semantic recall may not see files the underlying filestore
   surface hides (for example `_composted/` ephemeral code runs).
2. FRESHNESS AWARENESS — retrieval checks the current visible filestore against the
   index before use and may incrementally refresh when configured.

This is a recall layer, not the durable source of truth. The filestore remains the
memory surface; embeddings are a locator over that surface.
"""
from __future__ import annotations

import os
import threading

import swarm_filestore
import swarm_semantic


# Capture the core implementation before the active entry point optionally aliases
# any public semantic surface to this visibility-safe wrapper.
_CORE_REINDEX = swarm_semantic.reindex
_REINDEX_LOCK = threading.RLock()


def _bool_env(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def auto_refresh_enabled() -> bool:
    return _bool_env("RRI_SEMANTIC_AUTO_REFRESH", True)


def _visible_paths() -> list[str]:
    """Index candidates from the SAME visibility surface models can enumerate."""
    paths = []
    root = swarm_filestore._storage_root()
    for rel in swarm_filestore.list_files(""):
        p = root / rel
        if p.suffix.lower() not in swarm_semantic.INDEXABLE_EXTS:
            continue
        try:
            if p.stat().st_size > swarm_semantic.MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        paths.append(rel)
    return sorted(paths)


def _visible_walk():
    root = swarm_filestore._storage_root()
    for rel in _visible_paths():
        p = root / rel
        if p.exists() and p.is_file():
            yield p


def current_hashes() -> dict[str, str]:
    """Content hashes for every currently visible/indexable durable file."""
    root = swarm_filestore._storage_root()
    out: dict[str, str] = {}
    for rel in _visible_paths():
        p = root / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out[rel] = swarm_semantic._content_hash(text)
    return out


def freshness() -> dict:
    """Compare the semantic index manifest to the current visible memory surface.

    This is API-free. It reads local text and hashes it, which is the same cheap
    pre-pass core reindex already performs before deciding what actually needs an
    embedding call.
    """
    index = swarm_semantic._load_index()
    indexed = index.get("files") or {}
    current = current_hashes()

    current_paths = set(current)
    indexed_paths = set(indexed)
    added = sorted(current_paths - indexed_paths)
    removed = sorted(indexed_paths - current_paths)
    changed = sorted(
        rel for rel in current_paths & indexed_paths
        if indexed.get(rel, {}).get("content_hash") != current[rel]
    )
    dirty = bool(added or removed or changed)
    return {
        "fresh": not dirty,
        "built_at": index.get("built_at"),
        "indexed_files": len(indexed_paths),
        "visible_files": len(current_paths),
        "added": added,
        "changed": changed,
        "removed": removed,
        "auto_refresh_enabled": auto_refresh_enabled(),
    }


def reindex_visible(force: bool = False) -> dict:
    """Run the existing vector engine against model-visible filestore files only.

    We temporarily supply `_walk_filestore` with the visibility-aligned iterator and
    call the captured core reindex implementation. The swap is protected by a lock
    and restored in `finally`; no semantic logic is duplicated here.
    """
    with _REINDEX_LOCK:
        original_walk = swarm_semantic._walk_filestore
        swarm_semantic._walk_filestore = _visible_walk
        try:
            summary = _CORE_REINDEX(force=force)
        finally:
            swarm_semantic._walk_filestore = original_walk
    summary = dict(summary or {})
    summary["visibility_surface"] = "filestore.list_files"
    summary["freshness"] = freshness()
    return summary


def ensure_fresh() -> dict:
    """Refresh an out-of-date index when the current surface permits it."""
    before = freshness()
    if before["fresh"]:
        return {"ok": True, "refreshed": False, "freshness": before}

    if not auto_refresh_enabled():
        return {
            "ok": False,
            "refreshed": False,
            "freshness": before,
            "warning": "semantic index is stale; auto-refresh is disabled on this surface",
        }

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "ok": False,
            "refreshed": False,
            "freshness": before,
            "warning": "semantic index is stale; embedding credential is not exposed on this surface",
        }

    try:
        summary = reindex_visible(force=False)
    except Exception as exc:
        return {
            "ok": False,
            "refreshed": False,
            "freshness": before,
            "warning": f"semantic auto-refresh failed: {type(exc).__name__}: {exc}",
        }
    return {
        "ok": True,
        "refreshed": True,
        "reindex": summary,
        "freshness": freshness(),
    }


def search(query: str, top_k: int = 5, min_score: float = 0.0,
           filters: dict | None = None, hybrid: bool = False) -> dict:
    """Freshness-aware semantic search over the visible durable memory surface."""
    refresh = ensure_fresh()
    result = swarm_semantic.search(
        query=query,
        top_k=top_k,
        min_score=min_score,
        filters=filters,
        hybrid=hybrid,
    )
    out = dict(result or {})
    out["memory_index"] = refresh
    # Never return a result whose path no longer belongs to the visible surface,
    # even if an old/manual index left internal chunks behind.
    visible = set(_visible_paths())
    if isinstance(out.get("results"), list):
        out["results"] = [r for r in out["results"] if r.get("path") in visible]
        out["total_returned"] = len(out["results"])
    return out


def status() -> dict:
    base = swarm_semantic.status()
    base["freshness"] = freshness()
    base["visibility_surface"] = "filestore.list_files"
    return base


def tool_definitions() -> dict:
    """Native-tool definitions that replace the stale semantic-search surface."""
    return {
        "filestore_semantic_search": {
            "description": (
                "Meaning-based recall over the model-visible durable filestore. Use when lexical "
                "filestore_search misses because memory uses different wording. Before retrieval, "
                "the recall layer checks whether the embedding index matches the current visible "
                "memory surface and incrementally refreshes when that actuator/credential is "
                "available. Internal/composted files remain outside recall even if an older index "
                "once contained them. Results include memory_index freshness/refresh metadata; "
                "pair a returned path with filestore_read for the full durable record."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language memory query. Min 2 chars."},
                    "top_k": {"type": "integer", "description": "Number of hits to return, 1-20. Default 5."},
                    "min_score": {"type": "number", "description": "Optional cosine-similarity floor 0-1. Default 0."},
                    "filters": {
                        "type": "object",
                        "description": (
                            "Optional AND metadata filters over YAML frontmatter. Common keys: model, "
                            "type, status, session, source, tag/tags, dir, and after/before ISO dates."
                        ),
                    },
                    "hybrid": {
                        "type": "boolean",
                        "description": "Blend a small exact-keyword signal into vector ranking. Default false.",
                    },
                },
                "required": ["query"],
            },
            "dispatch": search,
        },
        "memory_index_status": {
            "description": (
                "Inspect the semantic recall index against the current model-visible durable memory "
                "surface. Returns build metadata plus added/changed/removed paths and whether "
                "auto-refresh is enabled. Use this to distinguish 'not retrieved' from 'not yet "
                "indexed' without treating either as absence of the underlying memory."
            ),
            "input_schema": {"type": "object", "properties": {}},
            "dispatch": status,
        },
    }
