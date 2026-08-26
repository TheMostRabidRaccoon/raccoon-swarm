"""Lease/capability state machine: epochs, proof, promotion, expiry, handoff."""

import json

import pytest

from growbot.harness.lease import LeaseError, LeaseManager, LeaseProof


def _manager(now):
    ids = iter(("lease_one", "lease_two", "lease_three"))
    proofs = iter(("proof-one", "proof-two", "proof-three"))
    return LeaseManager(clock_ms=lambda: now["ms"],
                        lease_id_fn=lambda epoch: next(ids),
                        proof_token_fn=lambda: next(proofs))


def _ack():
    return {"by": "kyra", "at": "2026-08-25T23:00:00Z"}


def test_new_lease_is_observe_only_and_proof_is_host_only():
    now = {"ms": 100}
    manager = _manager(now)
    grant = manager.issue("claude", ttl_ms=1000)
    assert grant.lease.state == "OBSERVE_ONLY"
    assert grant.lease.capabilities == ("OBSERVE_ONLY",)
    assert "proof-one" not in repr(grant.proof)
    with pytest.raises(TypeError):
        json.dumps(grant.proof)


def test_cannot_issue_competing_waking_lease():
    manager = _manager({"ms": 0})
    manager.issue("claude")
    with pytest.raises(LeaseError, match="revoked or faulted"):
        manager.issue("gpt")


def test_promotion_requires_prerequisites_and_human_ack():
    manager = _manager({"ms": 0})
    grant = manager.issue("claude")
    with pytest.raises(LeaseError, match="prerequisites"):
        manager.grant("SPEECH_GESTURE", grant.proof, ttl_ms=1000,
                      human_ack=_ack(), prerequisites_met=False)
    with pytest.raises(LeaseError, match="human_ack"):
        manager.grant("SPEECH_GESTURE", grant.proof, ttl_ms=1000,
                      human_ack=None, prerequisites_met=True)
    promoted = manager.grant("SPEECH_GESTURE", grant.proof, ttl_ms=1000,
                             human_ack=_ack(), prerequisites_met=True)
    assert promoted.state == "SPEECH_GESTURE"
    assert promoted.capabilities == ("OBSERVE_ONLY", "SPEECH_GESTURE")


def test_capabilities_expire_separately_and_locomotion_never_arrives_implicitly():
    now = {"ms": 0}
    manager = _manager(now)
    grant = manager.issue("claude", ttl_ms=10_000)
    manager.grant("SPEECH_GESTURE", grant.proof, ttl_ms=5_000,
                  human_ack=_ack(), prerequisites_met=True)
    manager.grant("LOCOMOTION_AUTHORIZED", grant.proof, ttl_ms=500,
                  human_ack=_ack(), prerequisites_met=True)
    assert manager.snapshot().state == "LOCOMOTION_AUTHORIZED"
    now["ms"] = 501
    assert manager.snapshot().state == "SPEECH_GESTURE"
    assert "LOCOMOTION_AUTHORIZED" not in manager.snapshot().capabilities


def test_locomotion_grant_cannot_outlive_speech_gesture_grant():
    now = {"ms": 0}
    manager = _manager(now)
    grant = manager.issue("claude", ttl_ms=10_000)
    manager.grant("SPEECH_GESTURE", grant.proof, ttl_ms=500,
                  human_ack=_ack(), prerequisites_met=True)
    manager.grant("LOCOMOTION_AUTHORIZED", grant.proof, ttl_ms=5_000,
                  human_ack=_ack(), prerequisites_met=True)
    now["ms"] = 501
    assert manager.snapshot().state == "OBSERVE_ONLY"
    assert manager.snapshot().capabilities == ("OBSERVE_ONLY",)


def test_locomotion_requires_active_speech_gesture_capability():
    manager = _manager({"ms": 0})
    grant = manager.issue("claude")
    with pytest.raises(LeaseError, match="requires an active SPEECH_GESTURE"):
        manager.grant("LOCOMOTION_AUTHORIZED", grant.proof, ttl_ms=100,
                      human_ack=_ack(), prerequisites_met=True)


def test_handoff_requires_quiesce_drain_and_terminal_state_then_increments_epoch():
    manager = _manager({"ms": 0})
    first = manager.issue("claude")
    assert manager.begin_quiesce(first.proof).state == "QUIESCING"
    with pytest.raises(LeaseError, match="drained"):
        manager.complete_revoke(first.proof, drained=False, body_terminal="limp")
    revoked = manager.complete_revoke(first.proof, drained=True, body_terminal="limp")
    assert revoked.state == "REVOKED"
    second = manager.issue("gpt")
    assert second.lease.epoch == first.lease.epoch + 1
    assert second.lease.state == "OBSERVE_ONLY"
    assert not manager.validate(first.proof, seat="claude", lease_id="lease_one", epoch=1).ok


def test_expiry_revokes_lease_and_invalidates_proof():
    now = {"ms": 0}
    manager = _manager(now)
    grant = manager.issue("claude", ttl_ms=100)
    now["ms"] = 100
    check = manager.validate(grant.proof, seat="claude",
                             lease_id=grant.lease.lease_id, epoch=grant.lease.epoch)
    assert not check.ok and check.reason == "lease expired"
    assert manager.snapshot().state == "REVOKED"


def test_fabricated_proof_and_wrong_seat_fail_even_with_copied_wire_fields():
    manager = _manager({"ms": 0})
    grant = manager.issue("claude")
    wire = grant.lease
    fabricated = LeaseProof("guessed")
    assert not manager.validate(fabricated, seat="claude",
                                lease_id=wire.lease_id, epoch=wire.epoch).ok
    assert not manager.validate(grant.proof, seat="fallback",
                                lease_id=wire.lease_id, epoch=wire.epoch).ok


def test_provider_fault_does_not_substitute_a_new_seat():
    manager = _manager({"ms": 0})
    grant = manager.issue("claude")
    faulted = manager.fault_current(expected_seat="claude", reason="timeout")
    assert faulted.state == "FAULTED"
    assert faulted.fault_reason == "timeout"
    assert manager.epoch == grant.lease.epoch
    assert manager.snapshot().seat == "claude"
    assert manager.snapshot().capabilities == ()
