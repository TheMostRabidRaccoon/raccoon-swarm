"""Append-only tick journal: the instrument of comparative ethology.

Every proposal, admission, rejection, and execution is a receipt attributed to
a seat. The journal is both the replay corpus (same ticks, different minds)
and the audit trail the RFC's acceptance tests read. brain_loop emits
proposed/admitted/rejected/executed; cancelled/expired arrive with Codex's
arbiter — the vocabulary is shared contract either way.

Append-only means append-only: no update or delete surface exists. Stdlib only.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

if __package__ in (None, ""):
    import contracts  # pragma: no cover
else:
    from . import contracts


class Journal:
    """JSONL receipts, one object per line. Pass path=None for in-memory."""

    def __init__(self, path=None, clock=time.time):
        self.path = Path(path) if path else None
        self._clock = clock
        self._memory = []

    def record(self, state, *, seat, tick_id, action_id=None, verb=None, reason=None, extra=None):
        if state not in contracts.JOURNAL_STATES:
            raise ValueError(f"unknown journal state {state!r}; have {contracts.JOURNAL_STATES}")
        entry = {"t": self._clock(), "state": state, "seat": seat, "tick_id": tick_id}
        if action_id is not None:
            entry["action_id"] = action_id
        if verb is not None:
            entry["verb"] = verb
        if reason is not None:
            entry["reason"] = reason
        if extra:
            entry.update(extra)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        else:
            self._memory.append(entry)
        return entry

    def entries(self):
        if self.path:
            if not self.path.exists():
                return []
            with open(self.path, encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        return list(self._memory)

    def states_for(self, tick_id):
        return [e["state"] for e in self.entries() if e["tick_id"] == tick_id]
