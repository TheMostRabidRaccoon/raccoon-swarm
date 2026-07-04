"""Persistent swarm memory — the cross-session JSON state layer.

Extracted from raccoon_swarm_server.py (leaf-first extraction, per the
Session-134 meta-eval sequence) so the merge logic is stdlib-only and
unit-testable. The server keeps extract_memory_delta (it needs the Claude
client); everything that touches swarm_memory.json lives here.

Three long-standing defects are fixed in this extraction — all three are
the "silent memory decay" the council banned while it was running:

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

# Max items to keep in each memory category before pruning old entries
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


def empty_memory() -> dict:
    """A fresh empty memory dict (lists are per-call copies)."""
    return {k: (list(v) if isinstance(v, list) else v) for k, v in _EMPTY_MEMORY.items()}


def load_swarm_memory() -> dict:
    """Load the swarm's persistent memory from disk.

    Bootstrap order: swarm_memory.json (runtime) > swarm_memory_seed.json (repo) > empty.
    """
    target = memory_file()
    if not target.exists() and MEMORY_SEED_FILE.exists():
        # First run: bootstrap from seed
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MEMORY_SEED_FILE, target)
        logger.info(f"Bootstrapped swarm memory from seed: {MEMORY_SEED_FILE}")

    if target.exists():
        try:
            with open(target, "r") as f:
                mem = json.load(f)
            # Ensure all keys exist (forward-compat)
            for key, default in _EMPTY_MEMORY.items():
                if key not in mem:
                    mem[key] = default if not isinstance(default, list) else []
            return mem
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load swarm memory: {e}")
            return empty_memory()
    return empty_memory()


def save_swarm_memory(memory: dict) -> None:
    """Write the swarm's persistent memory to disk."""
    target = memory_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    memory["last_updated"] = datetime.now().isoformat()
    # Prune oldest entries to keep memory bounded (lists are oldest-first, so
    # [-N:] keeps the newest). This cap is the ONE sanctioned forgetting
    # mechanism, and it is documented here rather than implicit anywhere else.
    memory["resolved_positions"] = memory["resolved_positions"][-MEMORY_MAX_RESOLVED:]
    memory["unresolved_questions"] = memory["unresolved_questions"][-MEMORY_MAX_UNRESOLVED:]
    memory["next_pursuits"] = memory["next_pursuits"][-MEMORY_MAX_PURSUITS:]
    memory["evolving_frameworks"] = memory["evolving_frameworks"][-MEMORY_MAX_FRAMEWORKS:]
    memory["session_log"] = memory["session_log"][-MEMORY_MAX_SESSION_LOG:]
    with open(target, "w") as f:
        json.dump(memory, f, indent=2)


def format_memory_context(memory: dict) -> str:
    """Format swarm memory into a prompt-injectable string.

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
        for pos in active_positions[-10:]:  # inject last 10 ACTIVE
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
    topic's tokens appear in the question. Topics are short ("verify_round_claims
    existence"); questions are long sentences — token containment is the signal,
    not symmetric similarity. Deliberately conservative: a false stay-open is
    recoverable (the extractor can name it next session); a false resolve
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
    """Merge extracted delta into persistent memory. Returns the saved memory
    (or None when the delta was empty)."""
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

    # Merge unresolved questions (increment attempts if question already exists)
    existing_qs = {_norm(q.get("question", "")): q for q in memory["unresolved_questions"]}
    for q in delta.get("unresolved_questions", []):
        key = _norm(q.get("question", ""))
        if key in existing_qs:
            existing_qs[key]["attempts"] = existing_qs[key].get("attempts", 1) + 1
        else:
            q["session"] = ts
            q["attempts"] = 1
            memory["unresolved_questions"].append(q)

    # MERGE next pursuits — new ones refresh, unexecuted ones carry forward.
    # (Previously: wholesale replacement, so any pursuit not re-extracted was
    # silently dropped. That was undocumented memory decay.)
    new_pursuits = delta.get("next_pursuits", [])
    if new_pursuits:
        for p in new_pursuits:
            p["session"] = ts
        new_keys = {_norm(p.get("direction", "")) for p in new_pursuits}
        carried = []
        for p in memory["next_pursuits"]:
            key = _norm(p.get("direction", ""))
            if not key or key in new_keys:
                continue  # re-stated: the fresh copy replaces it
            p["carried_sessions"] = p.get("carried_sessions", 0) + 1
            carried.append(p)
        # Stalest first so the documented cap drops carried-and-never-restated
        # pursuits before fresh ones.
        memory["next_pursuits"] = carried + new_pursuits

    # Evolving frameworks: update version if name matches, else add
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
    #   (a) explicit: the extractor names previously-open questions this
    #       session answered (delta["resolved_questions"], list of strings);
    #   (b) mechanical fallback: a new resolved position's topic answers the
    #       question by containment (the old exact-equality check between a
    #       full question sentence and a short topic string never fired).
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

    # Session log
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
