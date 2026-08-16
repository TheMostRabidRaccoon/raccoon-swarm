"""Read-only self-observation surface for the RRI peer cognitive ecology.

This module lets the running swarm inspect the source code and documentation that
constitute its current software environment without expanding its production write
surface. It deliberately separates OBSERVABILITY from ACTUATION:

- source_status/list/read/search expose evidence about the deployed checkout;
- no write, branch, merge, deploy, shell, or credential operation exists here;
- runtime data, secrets, user/personal corpus, and hidden state are outside this
  observation surface by construction.

The active entry point already installs this module's `tool_definitions()` as an
extension bundle. That bundle also composes in the memory-recall observation tools
from `swarm_recall`; this keeps the entry point small without conflating source and
memory as the same substrate.

A missing actuator is not a statement about model capability. It is simply a property
of the present interface.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent

# Source surfaces useful for understanding the swarm itself. Personal/runtime data
# and mutable external state are intentionally not part of source introspection.
_ALLOWED_ROOT_FILES = {
    "README.md",
    "CONTRIBUTING.md",
    "raccoon_swarm_server.py",
    "raccoon_mcp_server.py",
    "requirements.txt",
    "requirements-dev.txt",
    "runtime.txt",
}
_ALLOWED_ROOT_SUFFIXES = (".py",)
_ALLOWED_DIRS = ("docs", "tests", "scripts", "portfolio_factory", "systemd")
_ALLOWED_SUFFIXES = (".py", ".md", ".json", ".txt", ".yml", ".yaml", ".service", ".timer", ".path")

# Defense in depth. These should remain outside the surface even if a future allowed
# directory is broadened accidentally.
_DENIED_PARTS = {
    ".git", ".env", ".claude", "venv", ".venv", "__pycache__",
    "corpus", "journals", "music", "art_frames", "outputs", "logs", "vault",
    "swarm",  # runtime filestore when local storage happens to live under repo root
}
_DENIED_BASENAMES = {
    "swarm_memory.json",
    "swarm_memory_seed.json",
}


def _rel(path: Path) -> str:
    return path.relative_to(SOURCE_ROOT).as_posix()


def _is_allowed_rel(rel: str) -> bool:
    """Whether a repository-relative path belongs to the read-only source surface."""
    if not rel or rel.startswith("/"):
        return False
    parts = Path(rel).parts
    if any(part in (".", "..") for part in parts):
        return False
    if any(part.lower() in _DENIED_PARTS for part in parts):
        return False
    if parts[-1].lower() in _DENIED_BASENAMES:
        return False

    if len(parts) == 1:
        return rel in _ALLOWED_ROOT_FILES or Path(rel).suffix.lower() in _ALLOWED_ROOT_SUFFIXES

    if parts[0] not in _ALLOWED_DIRS:
        return False
    suffix = Path(parts[-1]).suffix.lower()
    return suffix in _ALLOWED_SUFFIXES


def _has_symlink_component(rel: str) -> bool:
    """Reject symlink-mediated observation, including symlinked parent dirs.

    The source surface is a lexical allowlist over the deployed checkout. A path like
    ``docs/leak.md`` must not acquire broader visibility merely because the filesystem
    redirects it to ``.env`` or outside the repository. Rejecting every symlink
    component keeps the observation boundary simple and auditable.
    """
    current = SOURCE_ROOT
    for part in Path(rel).parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            # An unreadable/ambiguous path is not promoted into observable source.
            return True
    return False


def _resolve(rel: str) -> Path | None:
    rel = (rel or "").strip().lstrip("/")
    if not _is_allowed_rel(rel) or _has_symlink_component(rel):
        return None

    root = SOURCE_ROOT.resolve()
    lexical = SOURCE_ROOT / rel
    try:
        target = lexical.resolve(strict=True)
        resolved_rel = target.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None

    # Re-apply the allow/deny policy to the resolved referent as defense in depth.
    # Even if symlink handling changes later, a lexically-allowed path may never
    # become a tunnel into a denied file such as .env.
    if not _is_allowed_rel(resolved_rel):
        return None
    return target


def _visible_files() -> list[Path]:
    out: list[Path] = []
    if not SOURCE_ROOT.exists():
        return out
    for p in SOURCE_ROOT.rglob("*"):
        try:
            rel = _rel(p)
        except ValueError:
            continue
        target = _resolve(rel)
        if target is None or not target.is_file():
            continue
        out.append(target)
    # De-duplicate defensively in case filesystem aliases ever appear without being
    # symlinks; expose each actual source referent only once.
    unique = {p: p for p in out}
    return sorted(unique.values(), key=lambda p: _rel(p))


def _git_sha() -> str | None:
    """Best available deployed-source identity, without network access."""
    for key in ("RRI_SOURCE_SHA", "RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA", "SOURCE_VERSION"):
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=SOURCE_ROOT,
            capture_output=True, text=True, timeout=2, check=True,
        )
        value = proc.stdout.strip()
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


def status() -> dict:
    files = _visible_files()
    return {
        "ok": True,
        "surface": "deployed-source/read-only",
        "source_sha": _git_sha(),
        "visible_files": len(files),
        "write_actuator": "not exposed on this surface",
        "canonical_semantics": "swarm_ecology.py",
        "note": (
            "This surface exposes source evidence only. Runtime memory, secrets, personal "
            "corpus, and production mutation are separate surfaces/routes."
        ),
    }


def list_files(prefix: str = "", max_results: int = 200) -> dict:
    prefix = (prefix or "").strip().lstrip("/")
    max_results = max(1, min(int(max_results), 500))
    matches = []
    for p in _visible_files():
        rel = _rel(p)
        if prefix and not (rel == prefix or rel.startswith(prefix.rstrip("/") + "/")):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        matches.append({"path": rel, "bytes": size})
        if len(matches) >= max_results:
            break
    return {"ok": True, "prefix": prefix or "(all)", "files": matches, "count": len(matches)}


def read(path: str, start_line: int = 1, end_line: int = 0) -> dict:
    target = _resolve(path)
    if target is None:
        return {"ok": False, "path": path, "error": "path is outside the source observation surface"}
    if not target.is_file():
        return {"ok": False, "path": path, "error": "source file not found on this checkout"}
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"ok": False, "path": path, "error": f"read failed: {type(exc).__name__}"}

    start = max(1, int(start_line or 1))
    if end_line:
        end = min(len(lines), max(start, int(end_line)))
    else:
        end = min(len(lines), start + 399)
    selected = lines[start - 1:end]
    numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(selected, start=start))
    return {
        "ok": True,
        "path": path,
        "source_sha": _git_sha(),
        "start_line": start,
        "end_line": end,
        "total_lines": len(lines),
        "content": numbered,
        "truncated": end < len(lines),
    }


def search(query: str, prefix: str = "", max_results: int = 20) -> dict:
    q = (query or "").strip()
    if len(q) < 2:
        return {"ok": False, "query": q, "error": "query must be at least 2 characters", "results": []}
    prefix = (prefix or "").strip().lstrip("/")
    max_results = max(1, min(int(max_results), 100))
    needle = q.lower()
    results: list[dict] = []

    for p in _visible_files():
        rel = _rel(p)
        if prefix and not (rel == prefix or rel.startswith(prefix.rstrip("/") + "/")):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, start=1):
            if needle not in line.lower():
                continue
            lo = max(1, idx - 1)
            hi = min(len(lines), idx + 1)
            snippet = "\n".join(f"{n}: {lines[n-1]}" for n in range(lo, hi + 1))
            results.append({"path": rel, "line": idx, "snippet": snippet})
            if len(results) >= max_results:
                return {
                    "ok": True, "query": q, "prefix": prefix or "(all)",
                    "source_sha": _git_sha(), "results": results, "truncated": True,
                }
    return {
        "ok": True, "query": q, "prefix": prefix or "(all)",
        "source_sha": _git_sha(), "results": results, "truncated": False,
    }


def _source_tool_definitions() -> dict:
    return {
        "source_status": {
            "description": (
                "Inspect the identity and scope of the swarm's current read-only deployed-source "
                "observation surface. Returns the best available source SHA and the number of "
                "visible source files. Use this before making claims about what code is currently "
                "running. This is observation, not a production-write surface."
            ),
            "input_schema": {"type": "object", "properties": {}},
            "dispatch": status,
        },
        "source_list": {
            "description": (
                "List files visible on the swarm's read-only deployed-source observation surface. "
                "Use this to inspect the actual software environment rather than infer source state "
                "from memory or old PR summaries. Runtime memory/secrets/personal corpus are outside "
                "this source surface."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "prefix": {"type": "string", "description": "Optional source path prefix such as 'docs' or 'tests'."},
                    "max_results": {"type": "integer", "description": "Maximum files, 1-500. Default 200."},
                },
            },
            "dispatch": list_files,
        },
        "source_read": {
            "description": (
                "Read an exact file from the swarm's read-only deployed-source surface with line "
                "numbers. Use after source_list/source_search when evaluating the actual runtime "
                "architecture, prompts, tools, tests, or docs. A read result is evidence about this "
                "checkout; it does not grant or imply a production mutation path."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Exact visible source path."},
                    "start_line": {"type": "integer", "description": "1-based first line. Default 1."},
                    "end_line": {"type": "integer", "description": "Optional 1-based last line; default returns up to 400 lines."},
                },
                "required": ["path"],
            },
            "dispatch": read,
        },
        "source_search": {
            "description": (
                "Search the swarm's current read-only deployed source for exact text and return "
                "line-numbered snippets. Use this for self-inspection: locate assumptions, prompt "
                "language, tool semantics, stale terminology, or implementation references before "
                "proposing a change."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Case-insensitive source text query, minimum 2 characters."},
                    "prefix": {"type": "string", "description": "Optional source path prefix."},
                    "max_results": {"type": "integer", "description": "Maximum matching lines, 1-100. Default 20."},
                },
                "required": ["query"],
            },
            "dispatch": search,
        },
    }


def tool_definitions() -> dict:
    """Active observation/recall extension bundle installed by the entry point."""
    out = _source_tool_definitions()
    # Lazy import avoids making source observation depend on embeddings/numpy merely
    # to import this module; tool construction happens after the runtime is loaded.
    try:
        import swarm_recall
        out.update(swarm_recall.tool_definitions())
    except Exception:
        # Source observation remains independently useful if the optional semantic
        # stack is unavailable on a minimal environment.
        pass
    return out
