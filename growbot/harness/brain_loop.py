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
    from growbot.harness import verbs as V
    from growbot.harness.body_client import BodyActuator, BodyClient, ConsoleActuator
else:
    from . import verbs as V
    from .body_client import BodyActuator, BodyClient, ConsoleActuator

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
    args = p.parse_args(argv)

    if not args.mock:
        p.error("only --mock is wired up so far; the live model path arrives with the swarm brain (phase 4a)")

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
