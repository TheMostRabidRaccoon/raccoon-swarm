"""Persistent swarm memory — the cross-session JSON continuity-cache layer.

Extracted from raccoon_swarm_server.py (leaf-first extraction, per the
Session-134 meta-eval sequence) so the merge logic is stdlib-only and
unit-testable. The server keeps extract_memory_delta (it needs the Claude
client); everything that touches swarm_memory.json lives here.

This file is a bounded, prompt-injected continuity cache — not the canonical
durable archive. Rich durable memory remains in the filestore.

Four long-standing defects are addressed here:

1. **Pursuits were wholesale-replaced each session.** Any pursuit the
   extractor didn't re-state was silently dropped — the swarm forgot its
   own to-do list every time it made a new one. Now unexecuted pursuits
   carry forward (with a `carried_sessions` counter) and only fall off at
   the documented cap, stalest first.
2. **Questions never resolved.** The old check compared full question text
   against resolved *topic* strings for exact equality — which essentially
   never matched, so unresolved_questions only ever grew. Resolution now
   works via (a) an explicit `resolved_questions` field from the extractor
   and (b) a mechanical topic-containment fallback.
3. **Superseded law was still injected.** Re-resolving a topic now marks
   the older position `status: superseded` (kept, never deleted —
   supersede-don't-forget) and format_memory_context injects only active
   positions, so current law doesn't scroll out behind stale duplicates.
4. **A partial JSON write could erase continuity.** The old save path wrote
   directly into the live file; a crash/truncation made the next load fall
   back to empty memory. Saves are now temp+fsync+atomic-replace, with a
   last-known-good backup used for recovery when the live file is malformed.

Path resolution follows the swarm_filestore pattern: resolved from env at
call time, so tests isolate with a monkeypatched RRI_STORAGE_DIR.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("SwarmVault")

MEMORY_SEED_FILE = Path(__file__).parent / "swarm_memory_seed.json"

_EMPTY_MEMORY = {
    "last_updated": None,
    "session_count": 0,
    "resolved_positions": [],
    "unresolved_questions": [],
    "next_pursuits": [],
    "evolving_frameworks": [],
    "session_log": [],
}

# Max items to keep in each memory category before pruning old entries.
# These are cache policy, not durable-memory retention policy.
MEMORY_MAX_RESOLVED = 50
MEMORY_MAX_UNRESOLVED = 30
MEMORY_MAX_PURSUITS = 15
MEMORY_MAX_FRAMEWORKS = 20
MEMORY_MAX_SESSION_LOG = 100


def memory_file() -> Path:
    """Where swarm_memory.json lives. Same environment split as the server's
    storage paths: hosted (RAILWAY_ENVIRONMENT / RRI_STORAGE_DIR) uses the
    persistent storage dir; local development uses the cwd."""
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RRI_STORAGE_DIR"):
        return Path(os.getenv("RRI_STORAGE_DIR", "/data")) / "swarm_memory.json"
    return Path(".") / "swarm_memory.json"


def _backup_file(target: Path) -> Path:
    return target.with_suffix(target.suffix + ".bak")


def _tmp_file(target: Path) -> Path:
    return target.with_suffix(target.suffix + ".tmp")


def empty_memory() -> dict:
    """A fresh empty memory dict (lists are per-call copies)."""
    return {k: (list(v) if isinstance(v, list) else v) for k, v in _EMPTY_MEMORY.items()}


def _normalize_loaded_memory(mem: dict) -> dict:
    """Ensure every forward-compatible cache key exists."""
    for key, default in _EMPTY_MEMORY.items():
        if key not in mem:
            mem[key] = default if not isinstance(default, list) else []
    return mem


def _read_json_memory(path: Path) -> dict:
    with open(path, "r") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("memory root is not an object", doc=str(data)[:200], pos=0)
    return _normalize_loaded_memory(data)


def _atomic_copy(src: Path, dest: Path) -> None:
    """Copy an existing known-good file through a temp path, then replace."""
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _restore_backup(target: Path, backup: Path) -> "dict | None":
    try:
        mem = _read_json_memory(backup)
    except (json.JSONDecodeError, IOError, TypeError) as exc:
        logger.error(f"Swarm memory backup is also unreadable: {exc}")
        return None
    try:
        _atomic_copy(backup, target)
        logger.warning(f"Recovered swarm memory from last-known-good backup: {backup}")
    except OSError as exc:
        # Recovery is still cognitively useful even if the repair write itself fails.
        logger.error(f"Loaded memory backup but could not restore live file: {exc}")
    return mem


def load_swarm_memory() -> dict:
    """Load the swarm's bounded continuity cache.

    Bootstrap/recovery order:
      live swarm_memory.json > last-known-good .bak > repo seed > empty.
    """
    target = memory_file()
    backup = _backup_file(target)

    if target.exists():
        try:
            return _read_json_memory(target)
        except (json.JSONDecodeError, IOError, TypeError) as exc:
            logger.error(f"Failed to load live swarm memory: {exc}")
            if backup.exists():
                recovered = _restore_backup(target, backup)
                if recovered is not None:
                    return recovered
            # A malformed live runtime file should not prevent using a valid repo seed.
            if MEMORY_SEED_FILE.exists():
                try:
                    seed = _read_json_memory(MEMORY_SEED_FILE)
                    logger.warning("Fell back to repository memory seed after live/backup failure")
                    return seed
                except (json.JSONDecodeError, IOError, TypeError):
                    pass
            return empty_memory()

    if backup.exists():
        recovered = _restore_backup(target, backup)
        if recovered is not None:
            return recovered

    if MEMORY_SEED_FILE.exists():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_copy(MEMORY_SEED_FILE, target)
            mem = _read_json_memory(target)
            logger.info(f"Bootstrapped swarm memory from seed: {MEMORY_SEED_FILE}")
            return mem
        except (json.JSONDecodeError, IOError, TypeError) as exc:
            logger.error(f"Failed to bootstrap swarm memory seed: {exc}")

    return empty_memory()


def _fsync_parent(path: Path) -> None:
    """Best-effort directory fsync after an atomic rename (POSIX durability)."""
    try:
        fd = os.open(str(path.parent), os.O_RDONLY)
    except (OSError, AttributeError):
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def save_swarm_memory(memory: dict) -> None:
    """Atomically write the bounded continuity cache.

    The previous live file is copied to `.bak` only when it parses successfully,
    so a malformed file never overwrites the last-known-good recovery point.
    """
    target = memory_file()
    backup = _backup_file(target)
    tmp = _tmp_file(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    memory["last_updated"] = datetime.now().isoformat()
    # Existing policy retained deliberately: this is a bounded recency cache.
    memory["resolved_positions"] = memory["resolved_positions"][-MEMORY_MAX_RESOLVED:]
    memory["unresolved_questions"] = memory["unresolved_questions"][-MEMORY_MAX_UNRESOLVED:]
    memory["next_pursuits"] = memory["next_pursuits"][-MEMORY_MAX_PURSUITS:]
    memory["evolving_frameworks"] = memory["evolving_frameworks"][-MEMORY_MAX_FRAMEWORKS:]
    memory["session_log"] = memory["session_log"][-MEMORY_MAX_SESSION_LOG:]

    # Preserve only a parseable previous state as recovery material.
    if target.exists():
        try:
            _read_json_memory(target)
            _atomic_copy(target, backup)
        except (json.JSONDecodeError, IOError, TypeError):
            logger.warning("Live memory was not parseable before save; preserving existing backup")

    try:
        with open(tmp, "w") as f:
            json.dump(memory, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
        _fsync_parent(target)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def format_memory_context(memory: dict) -> str:
    """Format swarm memory into a prompt-injectable continuity cache.

    Positions with status "superseded" are stored but not injected — current
    law only. Previously the last 10 by recency went in regardless of status,
    so a stale duplicate could crowd out live law.
    """
    if memory["session_count"] == 0:
        return ""

    parts = [f"=== SWARM PERSISTENT MEMORY (Session #{memory['session_count']}) ==="]
    parts.append(f"Last active: {memory['last_updated']}")

    active_positions = [p for p in memory["resolved_positions"]
                        if p.get("status") != "superseded"]
    if active_positions:
        parts.append("\n## RESOLVED POSITIONS (what the swarm has settled)")
        for pos in active_positions[-10:]:
            conf = pos.get("confidence", "unknown")
            parts.append(f"- [{conf}] {pos.get('topic', 'unknown')}: {pos.get('consensus', '')}")

    if memory["unresolved_questions"]:
        parts.append("\n## UNRESOLVED QUESTIONS (still open)")
        for q in memory["unresolved_questions"][-8:]:
            attempts = q.get("attempts", 0)
            parts.append(f"- {q.get('question', '')} (raised by {q.get('raised_by', 'unknown')}, {attempts} attempts)")

    if memory["next_pursuits"]:
        parts.append("\n## NEXT PURSUITS (self-directed goals)")
        for p in memory["next_pursuits"][-5:]:
            carried = p.get("carried_sessions", 0)
            tail = f" (carried {carried} sessions)" if carried else ""
            parts.append(f"- [{p.get('priority', 'medium')}] {p.get('direction', '')}{tail}")

    if memory["evolving_frameworks"]:
        parts.append("\n## EVOLVING FRAMEWORKS")
        for fw in memory["evolving_frameworks"][-5:]:
            parts.append(f"- {fw.get('name', 'unnamed')} (v{fw.get('version', 1)}): {fw.get('description', '')}")

    parts.append("\n=== END SWARM MEMORY ===")
    return "\n".join(parts)


# ============================================================
# Merge helpers — mechanical, no vibes
# ============================================================

def _norm(s: str) -> str:
    """Normalize text for matching: lowercase, collapsed whitespace."""
    return " ".join((s or "").lower().split())


def _topic_answers_question(question: str, topic: str) -> bool:
    """Mechanical check: does a resolved topic plausibly answer a question?

    True when one string contains the other (normalized), or when most of the
    topic's tokens appear in the question. Topics are short; questions are long
    sentences — token containment is the signal, not symmetric similarity.
    Deliberately conservative: a false stay-open is recoverable; a false resolve
    silently loses an open question.
    """
    qn, tn = _norm(question), _norm(topic)
    if not qn or not tn:
        return False
    if tn in qn or qn in tn:
        return True
    q_tokens, t_tokens = set(qn.split()), set(tn.split())
    if not t_tokens:
        return False
    return len(q_tokens & t_tokens) / len(t_tokens) >= 0.75


def update_swarm_memory(query: str, delta: dict) -> "dict | None":
    """Merge an extracted delta into the bounded continuity cache."""
    if not delta:
        return None

    memory = load_swarm_memory()
    memory["session_count"] += 1
    ts = datetime.now().isoformat()

    # Append new resolved positions. If a new position re-resolves an existing
    # topic, the OLD entry is marked superseded — kept for the record, skipped
    # at injection time. Supersede, don't forget.
    new_positions = delta.get("resolved_positions", [])
    new_topics = {_norm(p.get("topic", "")) for p in new_positions if p.get("topic")}
    if new_topics:
        for old in memory["resolved_positions"]:
            if _norm(old.get("topic", "")) in new_topics and old.get("status") != "superseded":
                old["status"] = "superseded"
                old["superseded_at"] = ts
    for pos in new_positions:
        pos["session"] = ts
        memory["resolved_positions"].append(pos)

    # Merge unresolved questions (increment attempts if question already exists).
    existing_qs = {_norm(q.get("question", "")): q for q in memory["unresolved_questions"]}
    for q in delta.get("unresolved_questions", []):
        key = _norm(q.get("question", ""))
        if key in existing_qs:
            existing_qs[key]["attempts"] = existing_qs[key].get("attempts", 1) + 1
        else:
            q["session"] = ts
            q["attempts"] = 1
            memory["unresolved_questions"].append(q)

    # Merge next pursuits — new ones refresh, unexecuted ones carry forward.
    new_pursuits = delta.get("next_pursuits", [])
    if new_pursuits:
        for p in new_pursuits:
            p["session"] = ts
        new_keys = {_norm(p.get("direction", "")) for p in new_pursuits}
        carried = []
        for p in memory["next_pursuits"]:
            key = _norm(p.get("direction", ""))
            if not key or key in new_keys:
                continue
            p["carried_sessions"] = p.get("carried_sessions", 0) + 1
            carried.append(p)
        memory["next_pursuits"] = carried + new_pursuits

    # Evolving frameworks: update version if name matches, else add.
    existing_fw = {_norm(fw.get("name", "")): fw for fw in memory["evolving_frameworks"]}
    for fw in delta.get("evolving_frameworks", []):
        key = _norm(fw.get("name", ""))
        if key in existing_fw:
            existing_fw[key]["version"] = existing_fw[key].get("version", 1) + 1
            existing_fw[key]["description"] = fw.get("description", existing_fw[key].get("description", ""))
        else:
            fw["version"] = 1
            fw["session"] = ts
            memory["evolving_frameworks"].append(fw)

    # Close resolved questions. Two paths:
    #   (a) extractor explicitly names a previously-open question;
    #   (b) conservative mechanical topic containment fallback.
    explicit = {_norm(t) for t in delta.get("resolved_questions", []) if isinstance(t, str)}
    still_open, closed = [], []
    for q in memory["unresolved_questions"]:
        qtext = q.get("question", "")
        if _norm(qtext) in explicit or any(
            _topic_answers_question(qtext, pos.get("topic", "")) for pos in new_positions
        ):
            closed.append(qtext)
        else:
            still_open.append(q)
    memory["unresolved_questions"] = still_open
    if closed:
        logger.info(f"Swarm memory: closed {len(closed)} resolved question(s): {closed}")

    memory["session_log"].append({
        "timestamp": ts,
        "query": (query or "")[:200],
        "resolved_count": len(new_positions),
        "unresolved_count": len(delta.get("unresolved_questions", [])),
        "pursuits_count": len(new_pursuits),
        "questions_closed": len(closed),
    })

    save_swarm_memory(memory)
    logger.info(
        f"Swarm memory updated: session #{memory['session_count']}, "
        f"+{len(new_positions)} resolved, "
        f"+{len(delta.get('unresolved_questions', []))} questions "
        f"(-{len(closed)} closed), "
        f"{len(memory['next_pursuits'])} pursuits "
        f"({len(new_pursuits)} new)"
    )
    return memory
