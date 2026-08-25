"""Provider-neutral seat adapters: any Council model can hold the waking seat.

Claude's package under EMBODIMENT_RFC.md §11. A seat adapter turns one
TickInput into one ActionOutput — nothing more. It holds no lease logic, no
safety logic, no actuation: the lease state machine and arbiter (Codex's
packages) sit between a seat's proposal and anything real.

Two mock seats with deliberately different temperaments ship here so the
logical-#101 demonstration — same recorded tick, different proposals,
identical deterministic dispositions — runs with zero API keys and zero
hardware. Live provider seats plug in later via CallableSeat, wrapping the
repo's existing model dispatch rather than reimplementing auth five times.

Stdlib only.
"""

from __future__ import annotations

import uuid

if __package__ in (None, ""):
    import contracts  # pragma: no cover
else:
    from . import contracts


def _default_id_fn():
    return "act_" + uuid.uuid4().hex[:12]


class SeatAdapter:
    """One model's occupancy of the waking seat. Subclasses implement propose()."""

    name = "seat"

    def propose(self, tick: "contracts.TickInput") -> "contracts.ActionOutput":
        raise NotImplementedError


class MockSeat(SeatAdapter):
    """A deterministic seat with a temperament. No model call, no keys.

    Styles are deliberately distinct so two seats given the same tick produce
    visibly different proposals — the seed of the comparative-ethology corpus.
    """

    STYLES = {
        "precise": {
            "greeting": "hello. I am awake, and I have posture opinions.",
            "gesture": [{"l": 70, "r": 110, "ms": 600}, {"l": 90, "r": 90, "ms": 400}],
            "quiet_moves": False,
        },
        "feral": {
            "greeting": "AWAKE. everything is a sock and I love it.",
            "gesture": [{"l": 120, "r": 55, "ms": 200}, {"l": 60, "r": 125, "ms": 200},
                        {"l": 115, "r": 60, "ms": 200}, {"l": 90, "r": 90, "ms": 300}],
            "quiet_moves": True,
        },
    }

    def __init__(self, style="precise", id_fn=_default_id_fn):
        if style not in self.STYLES:
            raise ValueError(f"unknown mock style {style!r}; have {sorted(self.STYLES)}")
        self.name = f"mock-{style}"
        self.style = self.STYLES[style]
        self._id_fn = id_fn

    def propose(self, tick):
        quiet = tick.event.get("kind") == "quiet_beat"
        verbs = []
        if not quiet:
            verbs.append({"v": "say", "args": {"text": self.style["greeting"]}})
        if not quiet or self.style["quiet_moves"]:
            verbs.append({"v": "gesture", "args": {"steps": self.style["gesture"]}})
        return contracts.ActionOutput(
            tick_id=tick.tick_id,
            lease_id=tick.lease_id,
            epoch=tick.epoch,
            action_id=self._id_fn(),
            verbs=tuple(verbs),
            journal_append=(
                {"kind": "observation", "text": f"{self.name} noticed: {tick.event.get('kind', 'a moment')}"},
            ),
            memory_proposal=None,
        )


class CallableSeat(SeatAdapter):
    """Wraps any callable(tick_dict) -> action_dict as a seat.

    This is the seam live providers plug into: hand it a closure over the
    repo's existing model dispatch and the reply is parsed — and rejected
    loudly — through the same contract as everything else.
    """

    def __init__(self, name, fn, id_fn=_default_id_fn):
        self.name = name
        self._fn = fn
        self._id_fn = id_fn

    def propose(self, tick):
        raw = self._fn(tick.to_dict())
        if isinstance(raw, dict):
            raw.setdefault("schema", contracts.SCHEMA_ACTION)
            raw.setdefault("tick_id", tick.tick_id)
            raw.setdefault("lease_id", tick.lease_id)
            raw.setdefault("epoch", tick.epoch)
            raw.setdefault("action_id", self._id_fn())
        return contracts.parse_action_output(raw)


def get_seat(spec, **kwargs):
    """Resolve a seat spec string: 'mock:precise', 'mock:feral'.

    Live provider specs ('claude', 'gpt', ...) arrive when the swarm dispatch
    is wired through CallableSeat — deliberately not stubbed with fakes here.
    """
    if spec.startswith("mock:"):
        return MockSeat(spec.split(":", 1)[1], **kwargs)
    if spec == "mock":
        return MockSeat("precise", **kwargs)
    raise ValueError(f"unknown seat spec {spec!r} — only mock:* seats exist until live adapters land")
