"""Verb contract for the GrowBot body: validate, clamp, budget.

The whole GrowBot design bet, kept intact here:

    the agent emits verbs -> body_truth defines the verbs -> the actuator executes them

The prompt is advisory; the clamp is code. Whatever model (or Council of models)
is talking, off-menu verbs are rejected, arguments are clamped to the body file's
hard limits, and motion is budgeted per tick and per rolling duty window.

Original implementation against the published body-truth format
(upstream agent-harness/SPEC-BODY-TRUTH.md). Stdlib only.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

DEFAULT_BODY_PATH = Path(__file__).parent / "body_truth_raccoon.json"


def load_body(path=DEFAULT_BODY_PATH):
    body = json.loads(Path(path).read_text())
    if body.get("format") != "growbot-body-truth":
        raise ValueError(f"{path} is not a growbot-body-truth file")
    return body


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def validate_verb(call, body):
    """Validate one verb call against the body's menu.

    Returns {"ok": True, "v", "motion", "args"} with args clamped to the machine
    face's hard limits, or {"ok": False, "why": reason}. Mirrors the reference
    harness semantics: off-menu -> reject; malformed -> reject; out-of-range
    numbers -> clamp, never crash (a hallucinated 999 means "far").
    """
    if not isinstance(call, dict) or not isinstance(call.get("v"), str):
        return {"ok": False, "why": "malformed verb call"}
    spec = next((v for v in body["verbs"] if v["v"] == call["v"]), None)
    if spec is None:
        return {"ok": False, "why": f"off-menu verb '{call['v']}'"}

    out = {}
    args = call.get("args") or {}
    for name, s in spec.get("args", {}).items():
        val = args.get(name)
        kind = s["type"]
        if kind == "string":
            if not isinstance(val, str) or not val.strip():
                return {"ok": False, "why": f"{spec['v']}.{name} must be a non-empty string"}
            if s.get("max_words"):
                val = " ".join(val.strip().split()[: s["max_words"]])
        elif kind == "enum":
            if val not in s["values"]:
                return {"ok": False, "why": f"{spec['v']}.{name}={val!r} not in enum"}
        elif kind == "number":
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                return {"ok": False, "why": f"{spec['v']}.{name} must be a number"}
            val = _clamp(val, s.get("min", float("-inf")), s.get("max", float("inf")))
        elif kind == "array":
            if not isinstance(val, list) or not val:
                return {"ok": False, "why": f"{spec['v']}.{name} must be a non-empty array"}
            val = [_clamp_item(item, s) for item in val[: s.get("max_items", len(val))]]
            if any(item is None for item in val):
                return {"ok": False, "why": f"{spec['v']}.{name} has a malformed item"}
            if s.get("max_total_ms"):
                val = _cap_total_ms(val, s["max_total_ms"])
        out[name] = val
    return {"ok": True, "v": spec["v"], "motion": bool(spec.get("motion")), "args": out}


def _clamp_item(item, spec):
    if not isinstance(item, dict):
        return None
    out = {}
    for field, rng in spec["items"].items():
        raw = item.get(field)
        if raw is None:
            if field in spec.get("required", []):
                return None
            continue  # optional field omitted: hold that channel
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            return None
        out[field] = _clamp(raw, rng[0], rng[1])
    return out


def _cap_total_ms(steps, max_total_ms):
    """Trim trailing steps once the cumulative ms budget is spent."""
    total, kept = 0, []
    for step in steps:
        total += step.get("ms", 0)
        if total > max_total_ms:
            break
        kept.append(step)
    return kept or steps[:1]


def motion_seconds(verb):
    """Rough duration of a validated motion verb, for duty accounting."""
    if verb["v"] == "gesture":
        return sum(s.get("ms", 0) for s in verb["args"]["steps"]) / 1000.0
    if verb["v"] == "walk":
        return float(verb["args"]["secs"])
    if verb["v"] == "rest":
        return 0.5
    return 0.0


class DutyMeter:
    """Rolling-window motion budget, enforced brain-side.

    Upstream's 20 s of motion per rolling 60 s is advisory in the phone app and
    absent from stock firmware, so this harness owns it. The actuator refuses
    past the cap - the model cannot spend what isn't there.
    """

    def __init__(self, motion_s=20.0, window_s=60.0, clock=time.monotonic):
        self.motion_s = motion_s
        self.window_s = window_s
        self._clock = clock
        self._spent = []  # (t, seconds) pairs

    def _prune(self, now):
        cutoff = now - self.window_s
        self._spent = [(t, s) for t, s in self._spent if t >= cutoff]

    def remaining(self):
        self._prune(self._clock())
        return max(0.0, self.motion_s - sum(s for _, s in self._spent))

    def allow(self, seconds):
        """True (and records the spend) if the budget covers this motion."""
        now = self._clock()
        self._prune(now)
        if sum(s for _, s in self._spent) + seconds > self.motion_s:
            return False
        self._spent.append((now, seconds))
        return True


def filter_tick(calls, body, duty=None):
    """Run one tick's verb list through the full contract.

    Returns (executed, rejections): validated+clamped verbs to actuate, and
    human-readable reasons for everything dropped. Enforces the per-tick motion
    cap and, when a DutyMeter is given, the rolling duty window.
    """
    max_motion = body.get("limits", {}).get("max_motion_verbs_per_tick", 1)
    executed, rejections, motions = [], [], 0
    for call in calls if isinstance(calls, list) else []:
        v = validate_verb(call, body)
        if not v["ok"]:
            rejections.append(v["why"])
            continue
        if v["motion"]:
            motions += 1
            if motions > max_motion:
                rejections.append(f"{v['v']}: motion budget spent this tick")
                continue
            if duty is not None and not duty.allow(motion_seconds(v)):
                rejections.append(f"{v['v']}: duty window exhausted ({duty.motion_s:.0f}s/{duty.window_s:.0f}s)")
                continue
        executed.append(v)
    return executed, rejections
