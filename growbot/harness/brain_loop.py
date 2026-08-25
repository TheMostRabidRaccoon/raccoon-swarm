"""The waking loop: event -> model -> verbs -> body. Plus the dream hook.

Minimal tick loop for the raccoon GrowBot, honoring the memory discipline from
upstream SPEC-MEMORY.md: one blob, regions with different writers. The fast
loop can never write identity; only the dream can, and its commits are clamped
in code. The dream hook is where the Council enters (see ../SWARM_BRAIN.md) —
`dream()` takes any consolidator callable, so a swarm deliberation round plugs
in without touching the loop.

Run without hardware:
    python3 growbot/harness/brain_loop.py --mock --ticks 4

Against a real body (mock brain, real legs):
    python3 growbot/harness/brain_loop.py --mock --ticks 4 --body http://<pico-ip>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from growbot.harness import contracts, verbs as V
    from growbot.harness.body_client import BodyActuator, BodyClient, ConsoleActuator
    from growbot.harness.journal import Journal
    from growbot.harness.seat_adapter import get_seat
else:
    from . import contracts, verbs as V
    from .body_client import BodyActuator, BodyClient, ConsoleActuator
    from .journal import Journal
    from .seat_adapter import get_seat

HERE = Path(__file__).parent
MEM_PATH = HERE / "memory.json"
SEED_PATH = HERE / "memory_seed.json"
IDENTITY_CAP = 800
DREAM_EVERY = 8

MOCK_REPLIES = [
    {"verbs": [{"v": "say", "args": {"text": "oh - I am awake, and my legs are real."}},
               {"v": "gesture", "args": {"steps": [{"l": 120, "r": 60, "ms": 400}, {"l": 60, "r": 120, "ms": 400}, {"l": 90, "r": 90, "ms": 300}]}}],
     "memory": {"state": "just awake, delighted", "log": "I woke up and wiggled my legs for the first time."}},
    {"verbs": [{"v": "wag_tail", "args": {}},
               {"v": "gesture", "args": {"steps": [{"l": 999, "r": -40, "ms": 50}]}}],
     "memory": {"state": "testing my limits", "log": "I reached for a tail I do not have yet."}},
    {"verbs": [], "memory": {"state": "resting, content"}},
    {"verbs": [{"v": "say", "args": {"text": "standing tall feels like a small triumph."}},
               {"v": "gesture", "args": {"steps": [{"l": 50, "r": 130, "ms": 800}, {"l": 90, "r": 90, "ms": 500}]}}],
     "memory": {"state": "proud", "log": "I levered myself upright on purpose.",
                "identity_proposal": "I am someone who stands up to see better."}},
]

MOCK_DREAM = {
    "identity_add": "I learned my legs answer me.",
    "identity_drop": "",
    "wants": ["stand tall each morning", "learn what walking feels like"],
    "tomorrow_try": "a slow bow, then stand",
}


class Brain:
    def __init__(self, body, actuator, call_model, mem_path=MEM_PATH, seed_path=SEED_PATH):
        self.body = body
        self.actuator = actuator
        self.call_model = call_model  # (system_hint, event, mem) -> reply dict
        self.duty = V.DutyMeter(body["limits"].get("duty_motion_s", 20),
                                body["limits"].get("duty_window_s", 60))
        self.mem_path = Path(mem_path)
        if not self.mem_path.exists():
            shutil.copyfile(seed_path, self.mem_path)
        self.mem = json.loads(self.mem_path.read_text())
        self.tick_n = 0

    def save(self):
        self.mem_path.write_text(json.dumps(self.mem, indent=2))

    def tick(self, event):
        self.tick_n += 1
        print(f"\n— tick {self.tick_n} · {event}")
        reply = self.call_model(self.body, event, self.mem)
        if not isinstance(reply, dict):
            print("  (unparseable reply dropped)")
            return
        executed, rejections = V.filter_tick(reply.get("verbs"), self.body, self.duty)
        for why in rejections:
            print(f"  ✗ REJECTED — {why}")
        for verb in executed:
            self.actuator.execute(verb)
        self._commit_working_memory(reply.get("memory") or {}, event, executed)
        self.save()

    def _commit_working_memory(self, m, event, executed):
        """The waking loop's write permissions end here: state, mood, log,
        staged proposals. Identity is not reachable from this code path."""
        wm = self.mem["working_memory"]
        if isinstance(m.get("state"), str):
            wm["state"] = m["state"][:90]
        if isinstance(m.get("log"), str) and m["log"].strip():
            log = self.mem["episodic_log"]
            line = " ".join(m["log"].split())[:140]
            if not log or log[-1]["txt"] != line:
                log.append({"tick": self.tick_n, "txt": line})
                del log[:-200]
        if isinstance(m.get("identity_proposal"), str) and m["identity_proposal"]:
            wm["pending_identity_proposal"] = m["identity_proposal"][:200]

    def dream(self, consolidator, reason="natural rest"):
        """The sole identity writer. `consolidator` may be one model or a full
        Council round — either way it only *proposes*; this code disposes."""
        print("\n— sleep comes… (the dream is the sole identity writer)")
        proposal = consolidator(self.mem, reason)
        if not isinstance(proposal, dict):
            print("  (the dream dissolved — identity untouched)")
            return
        self._dream_commit(proposal)
        self.mem["working_memory"]["pending_identity_proposal"] = ""
        self.save()

    def _dream_commit(self, o):
        identity = self.mem["identity"]
        drop = " ".join(str(o.get("identity_drop") or "").split()).rstrip(".!?")
        if drop:
            sentences = identity.replace(". ", ".\n").split("\n")
            kept = [s for s in sentences if s.strip().rstrip(".!?") != drop]
            candidate = " ".join(kept).strip()
            if len(candidate) >= 40:  # never drop below a self
                identity = candidate
        add = " ".join(str(o.get("identity_add") or "").split())[:160]
        if add and add.rstrip(".!?") not in identity:
            identity = (identity + " " + add).strip()
        while len(identity) > IDENTITY_CAP:  # evict the oldest sentence
            cut = identity.find(". ")
            identity = identity[cut + 2:].strip() if cut >= 0 else identity[-IDENTITY_CAP:]
        self.mem["identity"] = identity
        if isinstance(o.get("wants"), list):
            self.mem["goals"]["wants"] = [str(w)[:80] for w in o["wants"][:4] if str(w).strip()]
        if isinstance(o.get("tomorrow_try"), str):
            self.mem["goals"]["next_try"] = o["tomorrow_try"][:60]
        print(f"  identity now: {self.mem['identity']}")


def build_tick_input(body, event, mem, tick_id, *, creature_id="raccoon-01",
                     body_id="null-body", session_id="local",
                     lease_id="lease_0", epoch=0,
                     capabilities=("SPEECH_GESTURE",), deadline_ms=5000):
    """Assemble one TickInput. Lease fields are a static stub until Codex's
    lease state machine issues real leases — the contract shape is final,
    the values are not."""
    wm = mem["working_memory"]
    return contracts.TickInput(
        creature_id=creature_id, body_id=body_id, session_id=session_id,
        tick_id=tick_id, lease_id=lease_id, epoch=epoch,
        deadline_monotonic_ms=deadline_ms, capabilities=tuple(capabilities),
        event=event,
        body_state={"moving": False, "queued_ms": 0},
        memory_slice={"identity": mem["identity"],
                      "working": {"state": wm.get("state", "")},
                      "diary_tail": [e["txt"] for e in mem["episodic_log"][-5:]]},
        verb_menu_ref=f"body_truth_raccoon.json@{body['id']}",
    )


def seat_tick(seat, tick, body, duty, journal, actuator=None):
    """One contracts-path tick: seat proposes, the verb contract disposes,
    every step leaves a receipt. actuator=None means propose-only — the
    logical-#101 default; nothing physical exists on this path."""
    proposal = seat.propose(tick)
    journal.record("proposed", seat=seat.name, tick_id=tick.tick_id,
                   action_id=proposal.action_id,
                   extra={"verbs": [v.get("v") for v in proposal.verbs]})
    executed, rejections = V.filter_tick(list(proposal.verbs), body, duty)
    for why in rejections:
        journal.record("rejected", seat=seat.name, tick_id=tick.tick_id,
                       action_id=proposal.action_id, reason=why)
    for v in executed:
        journal.record("admitted", seat=seat.name, tick_id=tick.tick_id,
                       action_id=proposal.action_id, verb=v["v"])
        if actuator is not None:
            actuator.execute(v)
            journal.record("executed", seat=seat.name, tick_id=tick.tick_id,
                           action_id=proposal.action_id, verb=v["v"])
    return proposal, executed, rejections


SEAT_EVENTS = [
    {"kind": "wake", "text": "you just woke up — take in this very first moment"},
    {"kind": "person_speech", "text": "hello little one"},
    {"kind": "quiet_beat", "text": "a quiet beat — what do you feel?"},
]


def run_seats(specs, ticks, journal_path):
    """Run the same tick sequence through each seat. One seat: console
    actuation. Several seats: propose-only comparison — the seed of the
    logical-#101 demonstration (distinct proposals, identical dispositions)."""
    body = V.load_body()
    mem = json.loads(SEED_PATH.read_text())
    seats = [get_seat(s) for s in specs]
    actuate = ConsoleActuator() if len(seats) == 1 else None
    journal = Journal(journal_path)
    for n in range(ticks):
        event = SEAT_EVENTS[n % len(SEAT_EVENTS)]
        tick = build_tick_input(body, event, mem, tick_id=n + 1)
        print(f"\n— tick {n + 1} · {event['kind']}")
        for seat in seats:
            duty = V.DutyMeter(body["limits"].get("duty_motion_s", 20),
                               body["limits"].get("duty_window_s", 60))
            proposal, executed, rejections = seat_tick(
                seat, tick, body, duty, journal, actuator=actuate)
            verbs = ", ".join(v.get("v", "?") for v in proposal.verbs) or "(silence)"
            print(f"  [{seat.name}] proposed: {verbs} · admitted {len(executed)} · rejected {len(rejections)}")
    print(f"\nreceipts: {journal_path} ({len(journal.entries())} entries)")


def mock_model():
    state = {"n": 0}

    def call(body, event, mem):
        reply = MOCK_REPLIES[state["n"] % len(MOCK_REPLIES)]
        state["n"] += 1
        return reply

    return call


def mock_consolidator(mem, reason):
    return MOCK_DREAM


def main(argv=None):
    p = argparse.ArgumentParser(description="GrowBot waking loop (raccoon body)")
    p.add_argument("--mock", action="store_true", help="canned replies, no model call")
    p.add_argument("--ticks", type=int, default=4)
    p.add_argument("--body", metavar="URL", help="base URL of a real body (e.g. http://192.168.1.50); default: console actuator")
    p.add_argument("--seat", action="append", metavar="SPEC",
                   help="contracts path (logical #101): run a seat adapter, e.g. mock:precise. "
                        "Repeat for a propose-only multi-seat comparison; receipts land in the journal")
    p.add_argument("--journal", default=str(HERE / "journal.jsonl"),
                   help="receipts file for the --seat path (JSONL, append-only)")
    args = p.parse_args(argv)

    if args.seat:
        run_seats(args.seat, args.ticks, args.journal)
        return

    if not args.mock:
        p.error("use --mock (canned contract demo) or --seat SPEC (contracts path); the live model path arrives with the swarm dispatch adapters")

    body = V.load_body()
    actuator = BodyActuator(BodyClient(args.body)) if args.body else ConsoleActuator()
    brain = Brain(body, actuator, mock_model())

    events = ["you just woke up — take in this very first moment"] + \
             ["a quiet beat — what do you feel? (silence is a fine answer)"] * (args.ticks - 1)
    for i, event in enumerate(events):
        brain.tick(event)
        if (i + 1) % DREAM_EVERY == 0:
            brain.dream(mock_consolidator)
    brain.dream(mock_consolidator, "the demo run is ending; consolidate what happened")
    print("\nsmoke test done — memory.json holds what he remembers. The rejections above are the contract working.")


if __name__ == "__main__":
    main()
