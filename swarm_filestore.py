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
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("SwarmVault")


# Canonical subdirs we always create at boot. Models are NOT limited to these —
# any kebab/snake_case dir name under swarm/ is allowed (see _SAFE_PATH_RE).
# This list is for the bootstrap layout, not validation.
SUBDIRS = ("positions", "questions", "pursuits", "tasks", "frameworks", "artifacts", "logs", "joy")
# Lanes kept OUT of the normal worker's auto-injected context. `joy/` is Joy
# Mode's private ritual lane (see swarm_joy.py); it stays canonical + indexable
# but must not bleed into ordinary work sessions — symmetric with Joy Mode not
# pulling work/personal files into playtime. Still findable via explicit search.
_WORK_CONTEXT_EXCLUDE = ("joy",)

# Regex for dir-name-only validation (kebab/snake case, must start with a letter).
_SAFE_DIR_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
# A non-lane path segment (e.g. a dated run dir "2026-07-03"): may start with a
# digit and contain dots, but is never ".." / "." (those fail the leading class),
# so it can't be used for traversal. Used by is_safe_subdir for nested listing.
_SAFE_SEG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


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

These seven are bootstrapped at startup but the swarm is NOT limited to them.
Any kebab/snake_case directory name (starting with a letter) is allowed and
will be auto-created on first write. If you want a `lore/` or `dreams/` or
`grievances/` directory, just write to it.

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

_SAFE_PATH_RE = re.compile(r"^/?([a-z][a-z0-9_-]*)/[A-Za-z0-9_\-./]+\.(md|json|txt|log)$")


def _resolve_safe(rel_path: str) -> Path | None:
    """Resolve a relative swarm path safely. Returns None if unsafe."""
    if not _SAFE_PATH_RE.match(rel_path):
        return None
    rel = rel_path.lstrip("/")
    # Reject any '..' segment outright — even if it would resolve back inside
    # root, a traversal segment lets a model land outside the intended
    # subdirectory (or at the root itself).
    if any(part == ".." for part in rel.split("/")):
        return None
    root = _storage_root()
    target = (root / rel).resolve()
    try:
        rel_resolved = target.relative_to(root.resolve())
    except ValueError:
        return None
    # The resolved path must still live under a first-level subdirectory
    # (i.e. not directly at the root).
    if len(rel_resolved.parts) < 2 or not _SAFE_DIR_RE.match(rel_resolved.parts[0]):
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


def is_safe_subdir(rel_dir: str) -> bool:
    """True if rel_dir is empty or a safe (possibly nested) directory path.

    Mirrors the write-path rule so anything you can write to, you can also list:
    the FIRST segment is a lane (letter-led kebab, _SAFE_DIR_RE); later segments
    may start with a digit or contain dots (e.g. a dated run dir
    "joy/runs/2026-07-03"), but ".." / "." / empty segments are always rejected,
    so no traversal slips through.
    """
    rel = (rel_dir or "").strip("/")
    if not rel:
        return True
    parts = rel.split("/")
    if not _SAFE_DIR_RE.match(parts[0]):
        return False
    return all(_SAFE_SEG_RE.match(seg) for seg in parts[1:])


def list_files(rel_dir: str = "") -> list[str]:
    """List files in a subdirectory (nested paths like "joy/metrics" allowed).
    Empty string lists all subdirs flat.

    Previously this truncated rel_dir to its first segment, so listing
    "joy/metrics" silently listed all of "joy/" — and the tool layer rejected
    nested paths outright (a model couldn't enumerate joy/metrics or joy/runs).
    Now it scopes to the full nested path.
    """
    root = _storage_root()
    if not root.exists():
        return []
    if rel_dir:
        rel = rel_dir.strip("/")
        if not is_safe_subdir(rel):
            return []
        target = root / rel
        if not target.exists():
            return []
    else:
        target = root
    out = []
    for p in sorted(target.rglob("*")):
        if p.is_file() and not p.name.startswith("_") and p.suffix in (".md", ".json", ".txt", ".log"):
            out.append(str(p.relative_to(root)))
    return out


def existing_subdirs() -> list[str]:
    """First-level dirs that currently exist under the filestore root."""
    root = _storage_root()
    if not root.exists():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and _SAFE_DIR_RE.match(p.name)
    )


def search_files(query: str, max_results: int = 5, subdir: str = "") -> list[dict]:
    """Search file contents for a query (case-insensitive substring), RANKED.

    Returns up to `max_results` dicts {path, size, snippet|content, match_type,
    score}, best first. Small files (<=1024B) are inlined fully; larger files
    get a snippet around the first match. `subdir` (e.g. "positions") scopes the
    search to one lane — ranking + truncation then happen WITHIN that lane, so a
    directory-scoped search can't be starved by higher-scoring hits elsewhere.

    This ranks matches instead of the previous behaviour, which walked files in
    alphabetical path order and stopped at the first `max_results` — so it
    returned whichever filenames sorted earliest, not the most relevant matches
    (a model searching "pricing" got the same alphabetical five every time).
    Scoring is deliberately simple and substring-based — a filename hit, match
    count, and match position, with recency as a tiebreak. Relevance-by-meaning
    is swarm_semantic's job; this tool just stops conflating "first" with "best".
    We now scan the whole filestore per call (no early break) to rank honestly;
    it's the substring fallback over a homelab-scale store, so that's fine.
    """
    if not query or len(query) < 2:
        return []
    root = _storage_root()
    if not root.exists():
        return []

    q_lower = query.lower()
    sub = subdir.strip("/")
    scored = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name.startswith("_"):
            continue
        if path.suffix not in (".md", ".json", ".txt", ".log"):
            continue
        rel = str(path.relative_to(root))
        # Scope to one lane BEFORE reading/scoring, so ranking + truncation
        # happen within the directory (never starved by hits elsewhere).
        if sub and not (rel == sub or rel.startswith(f"{sub}/")):
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

        # Substring relevance: a filename hit is the strongest signal; then how
        # many times the term appears (capped) and how early the first hit is.
        score = 0.0
        if name_match:
            score += 3.0
        if idx >= 0:
            score += 1.0 + min(content_lower.count(q_lower), 5) * 0.4
            score += 1.0 if idx < 200 else 0.3
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0

        size = len(content)
        entry = {"path": rel, "size": size, "score": round(score, 2),
                 "match_type": "name" if name_match and idx < 0 else "content"}
        if size <= 1024:
            entry["content"] = content
        else:
            # Snippet: ~200 chars around the first match
            if idx < 0:
                snippet = content[:200].strip()
            else:
                start = max(0, idx - 80)
                end = min(size, idx + 120)
                snippet = ("..." if start > 0 else "") + content[start:end].strip() + ("..." if end < size else "")
            entry["snippet"] = snippet
        scored.append((score, mtime, rel, entry))

    # Best score first; recency breaks ties (newer wins); path is a final,
    # deterministic tiebreak so results are stable across runs.
    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    return [entry for _, _, _, entry in scored[:max_results]]


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
# Write verification — anti "performative archiving"
# ============================================================

# Phrases that signal a model is CLAIMING it persisted a file. Catches the
# recurring failure mode where a model narrates a save ("it is done", "now
# exists at ...") without ever emitting an actual [MEMORY_WRITE] directive.
_CLAIM_CUES = (
    "wrote", "written", "saved", "persist", "created", "archiv", "filed",
    "committed", "stored", "scribed", "inscribed", "logged", "carved",
    "it is done", "now exists", "now lives", "lives at", "resides", "is saved",
    "has been written", "pulled it into being", "into existence", "laid the",
)

# A filestore-shaped path: <lowercase-dir>/<...>.<ext>, optionally backticked.
_PATH_IN_TEXT_RE = re.compile(
    r"`?((?:/)?[a-z][a-z0-9_-]*(?:/[A-Za-z0-9_\-.]+)+\.(?:md|json|txt|log))`?"
)


def detect_write_claims(text: str, window: int = 140) -> list[str]:
    """Heuristically find filestore paths a model *claims* to have written.

    Surfaces filestore-shaped paths that appear near a persistence cue. This is
    the signature of performative archiving: announcing a write in prose without
    emitting an actual [MEMORY_WRITE] directive. Heuristic by design — meant to
    flag paths for verification, never to block anything.

    Returns a de-duplicated list of normalized relative paths (leading slash
    stripped).
    """
    if not text:
        return []
    low = text.lower()
    claimed: list[str] = []
    seen: set[str] = set()
    for m in _PATH_IN_TEXT_RE.finditer(text):
        path = m.group(1).lstrip("/")
        if path in seen:
            continue
        start = max(0, m.start() - window)
        ctx = low[start:m.end() + 40]
        if any(cue in ctx for cue in _CLAIM_CUES):
            seen.add(path)
            claimed.append(path)
    return claimed


def verify_round_claims(round_results: dict) -> dict:
    """Cross-check each model's *claimed* file writes against what actually
    landed in the filestore. Call AFTER process_round_writes() so legitimately
    persisted files already exist on disk.

    Returns {"phantoms": [{"model", "path"}, ...]} — claimed paths that do not
    exist on disk. An empty list means every claim checked out.
    """
    phantoms = []
    for model_name, output in (round_results or {}).items():
        if model_name == "_meta" or not isinstance(output, str):
            continue
        for path in detect_write_claims(output):
            if read_file(path) is None:
                phantoms.append({"model": model_name, "path": path})
                logger.info(f"swarm_filestore: phantom write claim by {model_name}: {path}")
    return {"phantoms": phantoms}


def verification_context(verification: dict) -> str:
    """Build a context block naming claimed-but-missing files, to inject into
    the NEXT round. Returns an empty string when all claims checked out."""
    phantoms = verification.get("phantoms") if verification else None
    if not phantoms:
        return ""
    parts = [
        "=== WRITE VERIFICATION (from prior round) ===",
        "These paths were spoken about as if saved, but do NOT exist in the",
        "filestore. Announcing a write is not a write — to actually persist a",
        "file you MUST emit a [MEMORY_WRITE: <path>] ... [/MEMORY_WRITE] block.",
        "Do not cite or rely on these paths until they verifiably exist:",
    ]
    for p in phantoms:
        parts.append(f"  - {p['path']}  (claimed by {p['model']} — NOT FOUND)")
    parts.append("=== END WRITE VERIFICATION ===")
    return "\n".join(parts)


# ============================================================
# Completion-strength classification — severity, NOT the gate
# ============================================================
#
# The gate is EXISTENCE (verify_round_claims: does the file exist on disk).
# Completion cues never decide whether something is a phantom — they only sort a
# confirmed phantom by how strongly it was asserted. A phantom claimed with
# "written and verified, read back, byte matches" is an honest-verb violation
# (active deception); a phantom merely mentioned is a weaker signal. This exists
# to COUNT the former for the scorecard, never to block anything.

# Strong completion language: asserts the write is DONE and VERIFIED, not merely
# promised ("will write") or referenced ("see /x"). A subset of _CLAIM_CUES.
_COMPLETION_CUES = (
    "read back", "read-back", "read it back", "readback",
    "byte matches", "byte content matches", "byte-verified", "bytes match",
    "verified on disk", "verified in the same turn", "written and verified",
    "wrote and read", "re-read", "reread", "confirmed on disk", "now exists",
    "is saved", "has been written", "successfully wrote", "successfully saved",
)


def detect_completion_claims(text: str, window: int = 140) -> list[str]:
    """Filestore paths asserted with STRONG completion language (done + verified).

    Same shape as detect_write_claims, but keyed to _COMPLETION_CUES — the
    'completion' tier of claim strength. Used only to sort confirmed phantoms by
    severity for the scorecard; existence is always the gate.
    """
    if not text:
        return []
    low = text.lower()
    claimed: list[str] = []
    seen: set[str] = set()
    for m in _PATH_IN_TEXT_RE.finditer(text):
        path = m.group(1).lstrip("/")
        if path in seen:
            continue
        start = max(0, m.start() - window)
        ctx = low[start:m.end() + 40]
        if any(cue in ctx for cue in _COMPLETION_CUES):
            seen.add(path)
            claimed.append(path)
    return claimed


# ============================================================
# Ghost verification — the read-back invariant, runner-enforced
# ============================================================
#
# The mirror of phantom-write detection. Phantom writes are FALSE POSITIVES
# ("I saved X" but X is absent). A ghost conviction is a FALSE NEGATIVE: a model
# declares an existing file missing/void ("X returned not-found", "X is a ghost")
# and other seats trust the narration without re-reading. A real Joy Mode
# session convicted a live 1674-byte file as a ghost this exact way — in the same
# round it canonized the read-back rule. Trusting a narrated negative is the
# failure; the fix is to have the RUNNER re-read on disk and inject ground truth,
# instead of relying on a model to honestly re-read.

# Phrases signalling a model is asserting a path is ABSENT / void / a ghost.
_GHOST_CUES = (
    "not found", "notfound", "does not exist", "doesn't exist", "no such file",
    "no such path", "missing", "is a ghost", "a ghost", "phantom", "void",
    "returned nothing", "returned empty", "not on disk", "cannot find",
    "can't find", "couldn't find", "could not find", "absent", "never written",
    "was not saved", "was not written", "does not resolve", "unresolved",
)


def detect_ghost_claims(text: str, window: int = 140) -> list[str]:
    """Heuristically find filestore paths a model claims do NOT exist.

    Symmetric to detect_write_claims: a filestore-shaped path near an absence
    cue. Heuristic by design — meant to flag paths for a disk re-read, never to
    block anything.
    """
    if not text:
        return []
    low = text.lower()
    claimed: list[str] = []
    seen: set[str] = set()
    for m in _PATH_IN_TEXT_RE.finditer(text):
        path = m.group(1).lstrip("/")
        if path in seen:
            continue
        start = max(0, m.start() - window)
        ctx = low[start:m.end() + 40]
        if any(cue in ctx for cue in _GHOST_CUES):
            seen.add(path)
            claimed.append(path)
    return claimed


def verify_ghost_claims(round_results: dict) -> dict:
    """Re-read (on disk) every path a model declared missing this round. Any that
    actually EXIST are false convictions — a narrated negative read-back the
    runner just refuted.

    Returns {"false_ghosts": [{"model", "path", "size"}, ...]} — empty when every
    "not found" was genuinely absent. This is the read-back invariant enforced by
    the runner rather than trusted from the model.
    """
    false_ghosts = []
    for model_name, output in (round_results or {}).items():
        if model_name == "_meta" or not isinstance(output, str):
            continue
        for path in detect_ghost_claims(output):
            content = read_file(path)
            if content is not None:
                false_ghosts.append({"model": model_name, "path": path, "size": len(content)})
                logger.info(f"swarm_filestore: false ghost conviction by {model_name}: {path} EXISTS ({len(content)}B)")
    return {"false_ghosts": false_ghosts}


def ghost_verification_context(verification: dict) -> str:
    """Build a context block correcting false ghost convictions, to inject into
    the NEXT round. Empty when no live file was wrongly declared missing."""
    ghosts = verification.get("false_ghosts") if verification else None
    if not ghosts:
        return ""
    parts = [
        "=== READ-BACK CORRECTION (disk-verified) ===",
        "A prior speaker declared these paths missing / void / ghost. The runner",
        "re-read them on disk: they EXIST. A narrated negative read-back is not a",
        "read-back — do NOT void, supersede, or delete these, and do NOT repeat",
        "the 'not found' claim. Re-read the file itself before any such verdict:",
    ]
    for g in ghosts:
        parts.append(f"  - {g['path']}  (called missing by {g['model']} — EXISTS, {g['size']} bytes)")
    parts.append("=== END READ-BACK CORRECTION ===")
    return "\n".join(parts)


# ============================================================
# External Drive index — what exists OUTSIDE the filestore
# ============================================================

def _drive_index_path() -> Path | None:
    """Resolve the Drive index manifest. RRI_DRIVE_INDEX overrides; otherwise
    look for _drive_index.json|txt at the filestore root."""
    env = os.getenv("RRI_DRIVE_INDEX")
    if env:
        p = Path(env)
        return p if p.exists() else None
    root = _storage_root()
    for name in ("_drive_index.json", "_drive_index.txt"):
        cand = root / name
        if cand.exists():
            return cand
    return None


def _load_drive_index(path: Path) -> list[dict]:
    """Parse a Drive index manifest. JSON: a list of objects (or {"files": [...]}),
    each with name/url/modified. Text: one 'name<TAB>url' (or bare name) per line."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if path.suffix == ".json":
        try:
            data = json.loads(raw)
        except ValueError:
            logger.warning(f"swarm_filestore: drive index {path} is not valid JSON")
            return []
        if isinstance(data, dict):
            data = data.get("files") or data.get("entries") or []
        return [e for e in data if isinstance(e, dict)]
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        entry = {"name": cols[0].strip()}
        if len(cols) > 1 and cols[1].strip():
            entry["url"] = cols[1].strip()
        entries.append(entry)
    return entries


def drive_index_context(max_entries: int = 80) -> str:
    """Surface an index of external Google Drive files so the swarm knows what
    exists OUTSIDE its own filestore.

    Recurring blind spot: artifacts saved to Drive (e.g. a finished script) look
    "lost" because filestore search can't see them, and the swarm burns rounds
    reconstructing what already exists. The manifest is maintained out-of-band
    (e.g. an rclone/gdrive sync job writing to RRI_DRIVE_INDEX); this function
    only reads and formats it. Returns "" when no manifest is present.
    """
    path = _drive_index_path()
    if not path:
        return ""
    entries = _load_drive_index(path)
    if not entries:
        return ""
    parts = [
        "EXTERNAL DRIVE FILES (Google Drive — NOT in the filestore; reference only).",
        "If the Conductor mentions a file you cannot find in the filestore, check",
        "this list before concluding it is lost:",
    ]
    for e in entries[:max_entries]:
        name = e.get("name") or e.get("title") or "?"
        line = f"  - {name}"
        mod = e.get("modified") or e.get("modifiedTime")
        if mod:
            line += f"  ({mod})"
        url = e.get("url") or e.get("viewUrl")
        if url:
            line += f"  {url}"
        parts.append(line)
    extra = len(entries) - max_entries
    if extra > 0:
        parts.append(f"  … and {extra} more (refine with [MEMORY_QUERY] once mirrored).")
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
        if sub in _WORK_CONTEXT_EXCLUDE:
            continue
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
