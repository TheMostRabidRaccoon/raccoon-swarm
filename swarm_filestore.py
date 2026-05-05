"""Swarm filestore — persistent shared memory the round-table swarm can write to.

Provides file read/write/search bounded to a `swarm/` directory under STORAGE_DIR,
plus a directive parser that extracts [MEMORY_WRITE] and [MEMORY_QUERY] blocks
from model outputs.

Integration model: after each loop round, the server calls process_round_writes()
to persist anything the models wrote, then process_round_queries() to fetch
matching content for injection into the next round's prompt.
"""
from __future__ import annotations

import os
import re
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("SwarmVault")


SUBDIRS = ("positions", "questions", "pursuits", "tasks", "frameworks", "artifacts", "logs")


def _storage_root() -> Path:
    """Resolve the swarm filestore root from env at call time (testable)."""
    base = os.getenv("RRI_STORAGE_DIR")
    if base:
        return Path(base) / "swarm"
    return Path(".") / "swarm"


def ensure_layout() -> Path:
    """Create the swarm directory tree if missing. Returns the root."""
    root = _storage_root()
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    readme = root / "_README.md"
    if not readme.exists():
        readme.write_text(_README_TEXT)
    return root


_README_TEXT = """# Swarm Filestore

This directory is the swarm's persistent shared memory. Files written here
survive across sessions and are visible to every model in the round table.

## Subdirectories

- `positions/` — resolved positions. Append-only by convention; do not overwrite.
- `questions/` — open questions, hypotheses, gaps.
- `pursuits/` — concrete next moves the swarm wants to investigate.
- `tasks/` — task files and assignments (Session 58 convention).
- `frameworks/` — named mental models, taxonomies, conceptual scaffolds.
- `artifacts/` — generated outputs: drafts, calculations, exhibits.
- `logs/` — per-session activity logs.

## Naming

Files use kebab-case slugs, optionally prefixed with date:
  `anansi-pricing.md`
  `2026-05-03_irs-refund-calc.md`

## Privacy

Do not write raw PHI here. If a memory entry references patient data,
write the structural insight, not the identifiers.
"""


# ============================================================
# Path safety
# ============================================================

_SAFE_PATH_RE = re.compile(r"^/?(positions|questions|pursuits|tasks|frameworks|artifacts|logs)/[A-Za-z0-9_\-./]+\.(md|json|txt|log)$")


def _resolve_safe(rel_path: str) -> Path | None:
    """Resolve a relative swarm path safely. Returns None if unsafe."""
    if not _SAFE_PATH_RE.match(rel_path):
        return None
    rel = rel_path.lstrip("/")
    root = _storage_root()
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


# ============================================================
# File ops
# ============================================================

def read_file(rel_path: str) -> str | None:
    target = _resolve_safe(rel_path)
    if target is None or not target.exists():
        return None
    try:
        return target.read_text()
    except OSError as e:
        logger.error(f"swarm_filestore.read_file failed for {rel_path}: {e}")
        return None


def write_file(rel_path: str, content: str) -> bool:
    target = _resolve_safe(rel_path)
    if target is None:
        logger.warning(f"swarm_filestore.write_file rejected unsafe path: {rel_path}")
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(content)
        tmp.replace(target)
        return True
    except OSError as e:
        logger.error(f"swarm_filestore.write_file failed for {rel_path}: {e}")
        return False


def append_file(rel_path: str, content: str) -> bool:
    target = _resolve_safe(rel_path)
    if target is None:
        logger.warning(f"swarm_filestore.append_file rejected unsafe path: {rel_path}")
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a") as f:
            if target.exists() and target.stat().st_size > 0:
                f.write("\n\n---\n\n")
            f.write(content)
        return True
    except OSError as e:
        logger.error(f"swarm_filestore.append_file failed for {rel_path}: {e}")
        return False


def list_files(rel_dir: str = "") -> list[str]:
    """List files in a subdirectory. Empty string lists all subdirs flat."""
    root = _storage_root()
    if not root.exists():
        return []
    if rel_dir:
        sub = rel_dir.strip("/").split("/")[0]
        if sub not in SUBDIRS:
            return []
        target = root / sub
    else:
        target = root
    out = []
    for p in sorted(target.rglob("*")):
        if p.is_file() and not p.name.startswith("_") and p.suffix in (".md", ".json", ".txt", ".log"):
            out.append(str(p.relative_to(root)))
    return out


def search_files(query: str, max_results: int = 5) -> list[dict]:
    """Search file contents for a query (case-insensitive substring).

    Returns a list of dicts: {path, snippet, full_content_if_small}.
    Per the consolidator design (Option B), small files are inlined fully;
    large files get a snippet around the first match.
    """
    if not query or len(query) < 2:
        return []
    root = _storage_root()
    if not root.exists():
        return []

    q_lower = query.lower()
    results = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("_"):
            continue
        if path.suffix not in (".md", ".json", ".txt", ".log"):
            continue
        try:
            content = path.read_text()
        except OSError:
            continue

        # Match on filename or content
        name_match = q_lower in path.stem.lower()
        content_lower = content.lower()
        idx = content_lower.find(q_lower)
        if not name_match and idx < 0:
            continue

        rel = str(path.relative_to(root))
        size = len(content)
        if size <= 1024:
            results.append({"path": rel, "size": size, "content": content, "match_type": "name" if name_match and idx < 0 else "content"})
        else:
            # Snippet: ~200 chars around the first match
            if idx < 0:
                snippet = content[:200].strip()
            else:
                start = max(0, idx - 80)
                end = min(size, idx + 120)
                snippet = ("..." if start > 0 else "") + content[start:end].strip() + ("..." if end < size else "")
            results.append({"path": rel, "size": size, "snippet": snippet, "match_type": "name" if name_match and idx < 0 else "content"})

        if len(results) >= max_results:
            break
    return results


# ============================================================
# Directive parsing
# ============================================================

# [MEMORY_WRITE: /positions/anansi-pricing.md]
# ...content...
# [/MEMORY_WRITE]
_WRITE_RE = re.compile(
    r"\[MEMORY_WRITE:\s*([^\]]+)\]\s*\n?(.*?)\n?\[/MEMORY_WRITE\]",
    re.DOTALL,
)

# [MEMORY_APPEND: /positions/anansi-pricing.md]
_APPEND_RE = re.compile(
    r"\[MEMORY_APPEND:\s*([^\]]+)\]\s*\n?(.*?)\n?\[/MEMORY_APPEND\]",
    re.DOTALL,
)

# [MEMORY_QUERY: anansi pricing]
# [/MEMORY_QUERY]
_QUERY_RE = re.compile(
    r"\[MEMORY_QUERY:\s*([^\]]+)\]\s*\n?(?:.*?\n?)?\[/MEMORY_QUERY\]",
    re.DOTALL,
)


def parse_directives(text: str) -> dict:
    """Extract memory directives from a model output.

    Returns: {"writes": [(path, content), ...], "appends": [...], "queries": [str, ...]}
    """
    if not text:
        return {"writes": [], "appends": [], "queries": []}
    writes = [(m.group(1).strip(), m.group(2).strip()) for m in _WRITE_RE.finditer(text)]
    appends = [(m.group(1).strip(), m.group(2).strip()) for m in _APPEND_RE.finditer(text)]
    queries = [m.group(1).strip() for m in _QUERY_RE.finditer(text)]
    return {"writes": writes, "appends": appends, "queries": queries}


# ============================================================
# Round integration — what the server calls
# ============================================================

def process_round_writes(round_results: dict) -> dict:
    """For each model's output in a round, persist any [MEMORY_WRITE] /
    [MEMORY_APPEND] directives. Returns a summary of what was persisted.

    `round_results` is the dict produced by run_loop_round() — model name -> output text.
    """
    ensure_layout()
    summary = {"writes": [], "appends": [], "rejected": []}
    for model_name, output in round_results.items():
        if model_name == "_meta" or not isinstance(output, str):
            continue
        directives = parse_directives(output)
        for path, content in directives["writes"]:
            ok = write_file(path, content)
            (summary["writes"] if ok else summary["rejected"]).append({"model": model_name, "path": path, "size": len(content)})
            if ok:
                logger.info(f"swarm_filestore: {model_name} wrote {path} ({len(content)} chars)")
        for path, content in directives["appends"]:
            ok = append_file(path, content)
            (summary["appends"] if ok else summary["rejected"]).append({"model": model_name, "path": path, "size": len(content)})
            if ok:
                logger.info(f"swarm_filestore: {model_name} appended to {path} ({len(content)} chars)")
    return summary


def process_round_queries(round_results: dict) -> str:
    """For each model's output, run any [MEMORY_QUERY] directives and return
    a single context block to inject into the NEXT round's prompt.

    Returns an empty string if no queries were issued or none matched.
    """
    if not round_results:
        return ""
    all_queries = []
    for model_name, output in round_results.items():
        if model_name == "_meta" or not isinstance(output, str):
            continue
        directives = parse_directives(output)
        for q in directives["queries"]:
            all_queries.append((model_name, q))

    if not all_queries:
        return ""

    parts = ["=== MEMORY QUERY RESULTS (from prior round) ==="]
    seen_paths = set()
    for model_name, q in all_queries:
        results = search_files(q, max_results=5)
        if not results:
            parts.append(f"\n## Query by {model_name}: {q!r}\n(no matches)")
            continue
        parts.append(f"\n## Query by {model_name}: {q!r}")
        for r in results:
            if r["path"] in seen_paths:
                continue
            seen_paths.add(r["path"])
            if "content" in r:
                parts.append(f"\n### {r['path']} (full, {r['size']} chars)\n{r['content']}")
            else:
                parts.append(f"\n### {r['path']} (snippet, full size {r['size']} chars)\n{r['snippet']}")
    parts.append("\n=== END MEMORY QUERY RESULTS ===")
    return "\n".join(parts)


# ============================================================
# Boot-time recently-written summary
# ============================================================

def recent_files_context(max_per_dir: int = 3) -> str:
    """Build a short context block listing the most recently written files
    per subdirectory. Lets the swarm know what's currently in memory without
    requiring a query."""
    root = _storage_root()
    if not root.exists():
        return ""
    parts = []
    for sub in SUBDIRS:
        target = root / sub
        if not target.exists():
            continue
        files = sorted(
            (p for p in target.rglob("*") if p.is_file() and not p.name.startswith("_") and p.suffix in (".md", ".json", ".txt", ".log")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:max_per_dir]
        if files:
            parts.append(f"  {sub}/: " + ", ".join(p.name for p in files))
    if not parts:
        return ""
    return "RECENT FILESTORE ENTRIES (use [MEMORY_QUERY: <keyword>] to fetch full content):\n" + "\n".join(parts)
