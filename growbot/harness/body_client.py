"""Client for the GrowBot phone<->body protocol (Path A: HTTP keyframe plans).

Speaks the open body protocol from upstream protocol/PROTOCOL.md to any
conforming board (reference: Pico 2 W running robot-server.py). The chip glides
between keyframes locally at 50 Hz; we send short *plans*, never per-tick poses.

Path B (the /ws pose stream that carries the trained walk policy) is
deliberately not here yet: the policy runner belongs with the brain process and
needs a websocket dependency. Until then, `walk` verbs are surfaced as a TODO
by the actuator rather than faked with a canned shuffle.

Brain-side self-limits from the protocol (plans <= 8 steps / <= 12000 ms, step
ms <= 3000, angles 0-180) are enforced here so a misbehaving brain still sends
legal traffic. Stdlib only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

MAX_PLAN_STEPS = 8
MAX_PLAN_MS = 12000
MAX_STEP_MS = 3000


class BodyError(RuntimeError):
    """The body answered with an error status."""


class QueueFullError(BodyError):
    """409: the chip's motion queue is full - back off and resend."""

    def __init__(self, queued_ms):
        super().__init__(f"body queue full ({queued_ms} ms queued)")
        self.queued_ms = queued_ms


class BodyClient:
    def __init__(self, base_url, timeout=3.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path, data=None):
        url = self.base_url + path
        req = urllib.request.Request(url, method="POST" if data is not None else "GET")
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, body, timeout=self.timeout) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def act(self, steps, mode="replace"):
        """POST a keyframe plan; returns queued_ms. The chip plays it at 50 Hz."""
        plan = []
        total = 0
        for step in steps[:MAX_PLAN_STEPS]:
            clean = {}
            for leg in ("l", "r"):
                if leg in step and step[leg] is not None:
                    clean[leg] = int(max(0, min(180, step[leg])))
            clean["ms"] = int(max(0, min(MAX_STEP_MS, step.get("ms", 0))))
            if total + clean["ms"] > MAX_PLAN_MS:
                break
            total += clean["ms"]
            plan.append(clean)
        if not plan:
            raise ValueError("empty plan")
        status, text = self._request("/act", {"steps": plan, "mode": mode})
        if status == 409:
            raise QueueFullError(_queued_ms(text))
        if status != 200:
            raise BodyError(f"/act -> {status}: {text[:120]}")
        return _queued_ms(text)

    def stop(self):
        """Instant hard stop: clear the queue, go limp. The brain's hard latch."""
        status, text = self._request("/stop")
        if status != 200:
            raise BodyError(f"/stop -> {status}: {text[:120]}")

    def pose(self, l=None, r=None):
        """One absolute pose now (500 ms dead-man on the chip)."""
        params = {}
        if l is not None:
            params["l"] = int(max(0, min(180, l)))
        if r is not None:
            params["r"] = int(max(0, min(180, r)))
        status, text = self._request("/pose?" + urllib.parse.urlencode(params))
        if status != 200:
            raise BodyError(f"/pose -> {status}: {text[:120]}")

    def routine(self, name):
        """Canned firmware gesture (wiggle/dance/...) - demos and smoke tests."""
        status, text = self._request("/routine?" + urllib.parse.urlencode({"name": name}))
        if status != 200:
            raise BodyError(f"/routine -> {status}: {text[:120]}")

    def stats(self):
        """The chip's only telemetry: health counters + motion queue state."""
        status, text = self._request("/stats")
        if status != 200:
            raise BodyError(f"/stats -> {status}: {text[:120]}")
        return json.loads(text)


def _queued_ms(text):
    try:
        return int(json.loads(text).get("queued_ms", 0))
    except (ValueError, AttributeError):
        return 0


class ConsoleActuator:
    """Stands in for the body when there is no hardware: prints what would move."""

    def execute(self, verb):
        icons = {"gesture": "🦵", "walk": "🚶", "rest": "😴", "say": "🗣"}
        print(f"  {icons.get(verb['v'], '▶')} {verb['v']} {json.dumps(verb['args'])}")


class BodyActuator:
    """Maps validated verbs onto protocol calls against a real body."""

    def __init__(self, client):
        self.client = client

    def execute(self, verb):
        if verb["v"] == "gesture":
            self.client.act(verb["args"]["steps"])
        elif verb["v"] == "rest":
            self.client.act([{"l": 90, "r": 90, "ms": 400}])
        elif verb["v"] == "walk":
            # Path B (policy streaming over /ws) is not wired up yet — see module docstring.
            print(f"  🚶 walk({verb['args']['secs']}s) requested — walk policy runner not wired up yet")
        elif verb["v"] == "say":
            print(f"  🗣 {verb['args']['text']}")
