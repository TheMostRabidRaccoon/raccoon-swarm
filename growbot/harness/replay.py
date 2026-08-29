"""Replay-only comparative runner with structural hardware isolation.

This module intentionally has no import path to body_client.  Its only sink is
NullBodyClient, an in-memory executor used to prove dispositions and
idempotency without constructing network or actuator machinery.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from . import contracts, verbs
from .arbiter import Arbiter
from .journal import Journal
from .lease import LeaseManager


DEFAULT_FIXTURE = Path(__file__).with_name("replay_fixture.json")


class NullBodyClient:
    """In-memory execution sink. It has no URL, socket, or hardware dependency."""

    def __init__(self):
        self.executed = []

    def execute(self, verb):
        self.executed.append(verb)


@dataclass(frozen=True)
class SeatReplay:
    seat: str
    proposals: tuple
    dispositions: tuple
    receipts: tuple
    null_executions: tuple


def load_fixture(path=DEFAULT_FIXTURE):
    raw = json.loads(Path(path).read_text())
    if raw.get("format") != "growbot-replay/0":
        raise ValueError("fixture must use growbot-replay/0")
    return tuple(contracts.parse_tick_input(t) for t in raw.get("ticks", []))


def replay_seats(seats, ticks, *, body=None, clock_ms=lambda: 0):
    """Run each seat in a fresh, identical deterministic world."""
    body = body or verbs.load_body()
    results = []
    for seat in seats:
        leases = LeaseManager(
            clock_ms=clock_ms, lease_id_fn=lambda epoch: f"replay_lease_{epoch}",
            proof_token_fn=lambda: "replay-host-proof")
        grant = leases.issue(seat.name, ttl_ms=60_000)
        leases.grant(
            "SPEECH_GESTURE", grant.proof, ttl_ms=60_000,
            human_ack={"by": "replay-fixture", "at": "recorded"},
            prerequisites_met=True)
        journal = Journal(clock=lambda: clock_ms() / 1000.0)
        null = NullBodyClient()
        arbiter = Arbiter(
            leases, body, journal, executor=null, clock_ms=clock_ms,
            duty=verbs.DutyMeter(20, 60, clock=lambda: clock_ms() / 1000.0))
        proposals, dispositions = [], []
        for recorded in ticks:
            current = leases.snapshot()
            tick = replace(
                recorded, lease_id=current.lease_id, epoch=current.epoch,
                capabilities=current.capabilities)
            proposal = seat.propose(tick)
            proposals.append(proposal)
            dispositions.append(arbiter.dispose(
                tick, proposal, seat=seat.name, proof=grant.proof))
        results.append(SeatReplay(
            seat.name, tuple(proposals), tuple(dispositions),
            tuple(journal.entries()), tuple(null.executed)))
    return tuple(results)
