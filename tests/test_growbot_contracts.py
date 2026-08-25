"""Contract schemas: structural validation, authority rules, round-trips."""

import pytest

from growbot.harness import contracts as C


def _tick_dict(**over):
    d = {
        "schema": C.SCHEMA_TICK, "creature_id": "r1", "body_id": "b1",
        "session_id": "s1", "tick_id": 1, "lease_id": "lease_1", "epoch": 1,
        "deadline_monotonic_ms": 5000, "capabilities": ["SPEECH_GESTURE"],
        "event": {"kind": "wake"}, "body_state": {}, "memory_slice": {},
        "verb_menu_ref": "body_truth_raccoon.json@x",
    }
    d.update(over)
    return d


def _action_dict(**over):
    d = {
        "schema": C.SCHEMA_ACTION, "tick_id": 1, "lease_id": "lease_1",
        "epoch": 1, "action_id": "act_1",
        "verbs": [{"v": "say", "args": {"text": "hi"}}],
        "journal_append": [], "memory_proposal": None,
    }
    d.update(over)
    return d


def test_tick_round_trip():
    tick = C.parse_tick_input(_tick_dict())
    assert C.parse_tick_input(tick.to_dict()) == tick


def test_tick_rejects_wrong_schema_and_unknown_capability():
    with pytest.raises(C.ContractError):
        C.parse_tick_input(_tick_dict(schema="growbot.tick/999"))
    with pytest.raises(C.ContractError):
        C.parse_tick_input(_tick_dict(capabilities=["ROOT"]))


def test_tick_rejects_bool_posing_as_int():
    with pytest.raises(C.ContractError):
        C.parse_tick_input(_tick_dict(tick_id=True))


def test_action_round_trip():
    action = C.parse_action_output(_action_dict())
    assert C.parse_action_output(action.to_dict()) == action


def test_action_rejects_identity_core_proposal():
    bad = _action_dict(memory_proposal={"region": "identity_core", "op": "append"})
    with pytest.raises(C.ContractError, match="identity_core"):
        C.parse_action_output(bad)


def test_action_allows_seat_journal_proposal():
    ok = _action_dict(memory_proposal={"region": "seat_journal", "op": "append"})
    assert C.parse_action_output(ok).memory_proposal["region"] == "seat_journal"


def test_action_rejects_malformed_verbs():
    with pytest.raises(C.ContractError):
        C.parse_action_output(_action_dict(verbs="soup"))
    with pytest.raises(C.ContractError):
        C.parse_action_output(_action_dict(verbs=["soup"]))


def test_handoff_beyond_observe_requires_human_ack():
    d = {
        "schema": C.SCHEMA_HANDOFF, "from_seat": "claude", "to_seat": "grok",
        "old_lease": "lease_1", "new_lease": "lease_2", "epoch": 2,
        "journal_snapshot_hash": "sha256:x", "drained": True,
        "body_terminal": "limp",
        "granted_capabilities": ["SPEECH_GESTURE"], "human_ack": None,
    }
    with pytest.raises(C.ContractError, match="human_ack"):
        C.parse_handoff(d)
    d["human_ack"] = {"by": "kyra", "at": "now"}
    assert C.parse_handoff(d).granted_capabilities == ("SPEECH_GESTURE",)


def test_handoff_observe_only_needs_no_ack():
    d = {
        "schema": C.SCHEMA_HANDOFF, "from_seat": "claude", "to_seat": "grok",
        "old_lease": "lease_1", "new_lease": "lease_2", "epoch": 2,
        "journal_snapshot_hash": "sha256:x", "drained": True,
        "body_terminal": "neutral",
        "granted_capabilities": ["OBSERVE_ONLY"], "human_ack": None,
    }
    assert C.parse_handoff(d).body_terminal == "neutral"


def test_dream_commit_requires_evidence_refs_and_valid_region():
    base = {
        "schema": C.SCHEMA_DREAM_COMMIT, "evidence_hash": "sha256:x",
        "commit_status": "commit", "dissents": [],
        "mutations": [{"region": "shared_memory", "op": "append",
                       "expected_version": 1, "proposer": "council",
                       "risk_class": "low", "approval_class": "dream",
                       "evidence_refs": ["diary:1"]}],
    }
    assert C.parse_dream_commit(base).commit_status == "commit"
    no_refs = dict(base)
    no_refs["mutations"] = [dict(base["mutations"][0], evidence_refs=[])]
    with pytest.raises(C.ContractError, match="evidence_refs"):
        C.parse_dream_commit(no_refs)
    bad_region = dict(base)
    bad_region["mutations"] = [dict(base["mutations"][0], region="soul")]
    with pytest.raises(C.ContractError):
        C.parse_dream_commit(bad_region)


def test_dream_commit_parked_dissent_needs_clock():
    d = {
        "schema": C.SCHEMA_DREAM_COMMIT, "evidence_hash": "sha256:x",
        "commit_status": "no_commit", "mutations": [],
        "dissents": [{"seat": "grok", "disposition": "parked"}],
    }
    with pytest.raises(C.ContractError, match="review_by"):
        C.parse_dream_commit(d)
    d["dissents"] = [{"seat": "grok", "disposition": "parked",
                      "review_by": "2026-09-30T00:00:00Z",
                      "on_expiry": "surface_for_disposition"}]
    assert C.parse_dream_commit(d).commit_status == "no_commit"


def test_dream_commit_status_vocabulary():
    d = {"schema": C.SCHEMA_DREAM_COMMIT, "evidence_hash": "x",
         "commit_status": "majority_rule", "mutations": [], "dissents": []}
    with pytest.raises(C.ContractError):
        C.parse_dream_commit(d)
