"""Replay fixture, comparative dispositions, and structural hardware isolation."""

import os
from pathlib import Path
import subprocess
import sys

from growbot.harness.replay import NullBodyClient, load_fixture, replay_seats
from growbot.harness.seat_adapter import MockSeat


ROOT = Path(__file__).resolve().parents[1]


def _ids(prefix):
    n = {"i": 0}

    def next_id():
        n["i"] += 1
        return f"{prefix}_{n['i']}"
    return next_id


def test_fixture_replays_two_minds_same_ticks_different_souls():
    ticks = load_fixture()
    results = replay_seats((
        MockSeat("precise", id_fn=_ids("precise")),
        MockSeat("feral", id_fn=_ids("feral")),
    ), ticks)
    precise, feral = results
    assert precise.proposals[0].verbs != feral.proposals[0].verbs
    assert [d.state for d in precise.dispositions] == ["executed", "executed"]
    assert [d.state for d in feral.dispositions] == ["executed", "executed"]
    assert all(e["state"] in {"proposed", "admitted", "executed"}
               for result in results for e in result.receipts)


def test_null_body_has_no_network_or_physical_client_surface():
    null = NullBodyClient()
    null.execute({"v": "say", "args": {"text": "receipt only"}})
    assert len(null.executed) == 1
    assert not hasattr(null, "url")
    assert not hasattr(null, "act")
    assert not hasattr(null, "stop")


def test_replay_import_succeeds_when_physical_body_module_is_forbidden():
    """A clean interpreter blocks body_client at import time; replay still runs."""
    code = r'''
import builtins
real_import = builtins.__import__
def isolated(name, *args, **kwargs):
    if name == "growbot.harness.body_client" or name.endswith(".body_client"):
        raise AssertionError("replay attempted to import physical body client")
    return real_import(name, *args, **kwargs)
builtins.__import__ = isolated
from growbot.harness.replay import load_fixture, replay_seats
from growbot.harness.seat_adapter import MockSeat
out = replay_seats((MockSeat("precise", id_fn=lambda: "a1"),), load_fixture())
assert len(out) == 1
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                          text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr
