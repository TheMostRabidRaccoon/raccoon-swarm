"""BodyClient against a fake Pico: protocol shapes, self-limits, error paths."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from growbot.harness.body_client import BodyClient, BodyError, QueueFullError


class FakePico(BaseHTTPRequestHandler):
    queue_full = False
    last_plan = None

    def _send(self, status, body, ctype="text/plain"):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/stop":
            self._send(200, "stopped")
        elif self.path.startswith("/stats"):
            self._send(200, json.dumps({"moving": False, "act": {"active": False, "queued_ms": 0}}), "application/json")
        elif self.path.startswith("/pose"):
            self._send(200, "ok")
        elif self.path.startswith("/routine"):
            self._send(404, '{"err":"unknown routine"}')
        else:
            self._send(404, "nope")

    def do_POST(self):
        if self.path != "/act":
            self._send(404, "nope")
            return
        plan = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakePico.last_plan = plan
        if FakePico.queue_full:
            self._send(409, json.dumps({"err": "queue full", "queued_ms": 14000}), "application/json")
        else:
            queued = sum(s.get("ms", 0) for s in plan["steps"])
            self._send(200, json.dumps({"ok": 1, "queued_ms": queued}), "application/json")

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def client():
    server = HTTPServer(("127.0.0.1", 0), FakePico)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield BodyClient(f"http://127.0.0.1:{server.server_port}")
    server.shutdown()


def test_act_returns_queued_ms(client):
    FakePico.queue_full = False
    queued = client.act([{"l": 120, "r": 60, "ms": 400}, {"l": 90, "r": 90, "ms": 300}])
    assert queued == 700
    assert FakePico.last_plan["mode"] == "replace"


def test_act_clamps_angles_and_step_ms(client):
    FakePico.queue_full = False
    client.act([{"l": 999, "r": -5, "ms": 9000}])
    step = FakePico.last_plan["steps"][0]
    assert step == {"l": 180, "r": 0, "ms": 3000}


def test_act_trims_plan_to_protocol_limits(client):
    FakePico.queue_full = False
    client.act([{"l": 90, "r": 90, "ms": 3000}] * 10)
    steps = FakePico.last_plan["steps"]
    assert len(steps) <= 8
    assert sum(s["ms"] for s in steps) <= 12000


def test_act_omitted_leg_not_sent(client):
    FakePico.queue_full = False
    client.act([{"l": 70, "ms": 300}])
    assert "r" not in FakePico.last_plan["steps"][0]


def test_empty_plan_raises(client):
    with pytest.raises(ValueError):
        client.act([])


def test_queue_full_raises_with_backoff_info(client):
    FakePico.queue_full = True
    with pytest.raises(QueueFullError) as e:
        client.act([{"l": 90, "r": 90, "ms": 200}])
    assert e.value.queued_ms == 14000
    FakePico.queue_full = False


def test_stop_and_stats(client):
    client.stop()
    stats = client.stats()
    assert stats["act"]["queued_ms"] == 0


def test_unknown_routine_raises(client):
    with pytest.raises(BodyError):
        client.routine("moonwalk")
