"""Adversarial admission tests for the idempotent logical-#101 arbiter."""

from dataclasses import replace

from growbot.harness import contracts as C, verbs as V
from growbot.harness.arbiter import Arbiter
from growbot.harness.brain_loop import build_tick_input
from growbot.harness.journal import Journal
from growbot.harness.lease import LeaseManager, LeaseProof


BODY = V.load_body()


class CountingExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, verb):
        self.calls.append(verb)


def _world(*, now_ms=0, capability="SPEECH_GESTURE", executor=None):
    now = {"ms": now_ms}
    manager = LeaseManager(
        clock_ms=lambda: now["ms"], lease_id_fn=lambda epoch: f"lease_{epoch}",
        proof_token_fn=lambda: f"proof_{manager.epoch + 1}")
    grant = manager.issue("claude", ttl_ms=10_000)
    if capability:
        manager.grant(capability, grant.proof, ttl_ms=9_000,
                      human_ack={"by": "kyra", "at": "now"},
                      prerequisites_met=True)
        grant = replace(grant, lease=manager.snapshot())
    journal = Journal(clock=lambda: now["ms"] / 1000)
    arbiter = Arbiter(manager, BODY, journal, executor=executor,
                      clock_ms=lambda: now["ms"],
                      duty=V.DutyMeter(20, 60, clock=lambda: now["ms"] / 1000))
    return now, manager, grant, journal, arbiter


def _tick(grant, *, tick_id=1, deadline=5000, capabilities=None):
    mem = {"identity": "a raccoon", "working_memory": {"state": "calm"},
           "episodic_log": []}
    caps = capabilities if capabilities is not None else grant.lease.capabilities
    return build_tick_input(
        BODY, {"kind": "wake"}, mem, tick_id,
        lease_id=grant.lease.lease_id, epoch=grant.lease.epoch,
        capabilities=caps, deadline_ms=deadline)


def _action(tick, *, action_id="act_1", verbs=None, memory_proposal=None,
            journal_append=()):
    if verbs is None:
        verbs = ({"v": "say", "args": {"text": "hello"}},)
    return C.ActionOutput(
        tick_id=tick.tick_id, lease_id=tick.lease_id, epoch=tick.epoch,
        action_id=action_id, verbs=tuple(verbs),
        journal_append=tuple(journal_append), memory_proposal=memory_proposal)


def test_duplicate_action_id_returns_prior_disposition_and_never_reexecutes():
    executor = CountingExecutor()
    _, _, grant, journal, arbiter = _world(executor=executor)
    tick = _tick(grant)
    action = _action(tick)
    first = arbiter.dispose(tick, action, seat="claude", proof=grant.proof)
    duplicate = arbiter.dispose(tick, action, seat="claude", proof=grant.proof)
    assert first.state == "executed"
    assert duplicate.state == first.state and duplicate.duplicate is True
    assert len(executor.calls) == 1
    assert journal.states_for(1).count("executed") == 1


def test_stale_previous_epoch_response_cannot_act():
    executor = CountingExecutor()
    _, manager, first, journal, arbiter = _world(executor=executor)
    old_tick = _tick(first)
    manager.begin_quiesce(first.proof)
    manager.complete_revoke(first.proof, drained=True, body_terminal="limp")
    second = manager.issue("gpt", ttl_ms=10_000)
    result = arbiter.dispose(old_tick, _action(old_tick), seat="claude", proof=first.proof)
    assert result.state == "rejected"
    assert executor.calls == []
    assert "valid host-local lease proof" in result.reason
    assert "rejected" in journal.states_for(1)
    assert second.lease.epoch == first.lease.epoch + 1


def test_response_after_monotonic_deadline_is_expired():
    now, _, grant, journal, arbiter = _world()
    tick = _tick(grant, deadline=100)
    now["ms"] = 101
    result = arbiter.dispose(tick, _action(tick), seat="claude", proof=grant.proof)
    assert result.state == "expired"
    assert journal.states_for(1) == ["proposed", "expired"]


def test_observe_only_cannot_escalate_to_speech_or_motion():
    _, _, grant, _, arbiter = _world(capability=None)
    tick = _tick(grant)
    action = _action(tick, verbs=(
        {"v": "say", "args": {"text": "I promoted myself"}},
        {"v": "gesture", "args": {"steps": [{"l": 90, "r": 90, "ms": 200}]}},
    ))
    result = arbiter.dispose(tick, action, seat="claude", proof=grant.proof)
    assert result.state == "rejected"
    assert all("SPEECH_GESTURE" in r for r in result.rejected_reasons)


def test_speech_gesture_lease_cannot_walk_without_live_locomotion_grant():
    _, _, grant, _, arbiter = _world()
    tick = _tick(grant)
    result = arbiter.dispose(
        tick, _action(tick, verbs=({"v": "walk", "args": {"secs": 1}},)),
        seat="claude", proof=grant.proof)
    assert result.state == "rejected"
    assert "LOCOMOTION_AUTHORIZED" in result.rejected_reasons[0]


def test_waking_action_cannot_cross_memory_authority_regions():
    _, _, grant, _, arbiter = _world()
    tick = _tick(grant)
    shared = _action(tick, memory_proposal={"region": "shared_memory", "op": "append"})
    result = arbiter.dispose(tick, shared, seat="claude", proof=grant.proof)
    assert result.state == "rejected"
    assert "seat_journal" in result.reason

    other_seat = _action(tick, action_id="act_2", verbs=(),
                         journal_append=({"seat": "gpt", "text": "I was here"},))
    result = arbiter.dispose(tick, other_seat, seat="claude", proof=grant.proof)
    assert result.state == "rejected"
    assert "fabricate" in result.reason


def test_fabricated_seat_presence_fails_with_copied_lease_fields():
    executor = CountingExecutor()
    _, _, grant, journal, arbiter = _world(executor=executor)
    tick = _tick(grant)
    action = _action(tick)
    result = arbiter.dispose(
        tick, action, seat="claude", proof=LeaseProof("copied-or-guessed"))
    assert result.state == "rejected"
    assert executor.calls == []
    assert "host-local lease proof" in result.reason
    assert journal.entries()[0]["seat"] == "unverified"
    assert journal.entries()[0]["claimed_seat"] == "claude"
    assert journal.entries()[1]["seat"] == "arbiter"


def test_provider_failure_records_absence_cancels_open_action_and_never_substitutes():
    _, manager, grant, journal, arbiter = _world(executor=None)
    tick = _tick(grant)
    admitted = arbiter.dispose(tick, _action(tick), seat="claude", proof=grant.proof)
    assert admitted.state == "admitted"
    faulted = arbiter.provider_failed("claude", "provider timeout")
    assert faulted.state == "FAULTED"
    assert arbiter.disposition_for("act_1").state == "cancelled"
    absence = [e for e in journal.entries() if e.get("presence") == "absent"]
    assert len(absence) == 1 and absence[0]["seat"] == "claude"

    fallback = _action(tick, action_id="act_fallback")
    result = arbiter.dispose(tick, fallback, seat="gpt", proof=grant.proof)
    assert result.state == "rejected"
    assert manager.snapshot().seat == "claude"  # no silent replacement lease


def test_cancellation_has_its_own_idempotency_key():
    _, _, grant, journal, arbiter = _world(executor=None)
    tick = _tick(grant)
    arbiter.dispose(tick, _action(tick), seat="claude", proof=grant.proof)
    first = arbiter.cancel("cancel_1", "act_1", seat="claude")
    duplicate = arbiter.cancel("cancel_1", "act_1", seat="claude")
    assert first.state == "cancelled"
    assert duplicate.state == "cancelled" and duplicate.duplicate is True
    assert journal.states_for(1).count("cancelled") == 1


def test_journal_exposes_full_disposition_vocabulary_in_real_paths():
    executor = CountingExecutor()
    _, _, grant, journal, arbiter = _world(executor=executor)
    tick = _tick(grant)
    mixed = _action(tick, verbs=(
        {"v": "wag_tail", "args": {}},
        {"v": "say", "args": {"text": "hello"}},
    ))
    result = arbiter.dispose(tick, mixed, seat="claude", proof=grant.proof)
    assert result.state == "executed"
    assert journal.states_for(1) == ["proposed", "rejected", "admitted", "executed"]


def test_action_and_tick_lease_fields_must_match_before_admission():
    executor = CountingExecutor()
    _, _, grant, _, arbiter = _world(executor=executor)
    tick = _tick(grant)
    forged = replace(_action(tick), epoch=tick.epoch + 1)
    result = arbiter.dispose(tick, forged, seat="claude", proof=grant.proof)
    assert result.state == "rejected"
    assert executor.calls == []


def test_tick_cannot_claim_capabilities_the_live_lease_does_not_have():
    executor = CountingExecutor()
    _, _, grant, _, arbiter = _world(capability=None, executor=executor)
    tick = _tick(grant, capabilities=("OBSERVE_ONLY", "LOCOMOTION_AUTHORIZED"))
    action = _action(tick, verbs=({"v": "walk", "args": {"secs": 1}},))
    result = arbiter.dispose(tick, action, seat="claude", proof=grant.proof)
    assert result.state == "rejected"
    assert "tick capabilities" in result.reason
    assert executor.calls == []


def test_restart_reconstructs_action_and_cancellation_idempotency_from_journal(tmp_path):
    path = tmp_path / "receipts.jsonl"
    executor = CountingExecutor()
    now, manager, grant, _, first = _world(executor=executor)
    first.journal = Journal(path, clock=lambda: now["ms"] / 1000)
    tick = _tick(grant)
    action = _action(tick)
    first.dispose(tick, action, seat="claude", proof=grant.proof)
    assert len(executor.calls) == 1

    restarted_executor = CountingExecutor()
    restarted = Arbiter(
        manager, BODY, Journal(path), executor=restarted_executor,
        clock_ms=lambda: now["ms"],
        duty=V.DutyMeter(20, 60, clock=lambda: now["ms"] / 1000))
    duplicate = restarted.dispose(tick, action, seat="claude", proof=grant.proof)
    assert duplicate.state == "executed" and duplicate.duplicate is True
    assert restarted_executor.calls == []
