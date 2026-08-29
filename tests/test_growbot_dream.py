"""The dream pipeline: blind passes, layered verification, clocked parking.

Every quarantine path here is the contract working — a dream that cannot
prove its own provenance never touches the soul file.
"""

import json
from pathlib import Path

import pytest

from growbot.harness import contracts as C, dream as D

SEED = json.loads(
    (Path(__file__).parent.parent / "growbot/harness/memory_seed.json").read_text())


def fresh_mem(diary=("I wiggled my legs.", "Kyra laughed.")):
    mem = json.loads(json.dumps(SEED))
    mem["episodic_log"] = [{"tick": i, "txt": t} for i, t in enumerate(diary)]
    return mem


def make_pass(proposal=None, concerns=()):
    def fn(packet):
        return {"proposal": proposal or {"summary": "a good day"},
                "concerns": list(concerns)}
    return fn


def make_synth(mutations=None, dissents=None, status="commit"):
    def fn(packet, passes):
        return {"schema": C.SCHEMA_DREAM_COMMIT,
                "evidence_hash": packet["evidence_hash"],
                "commit_status": status,
                "mutations": mutations if mutations is not None else [{
                    "region": "shared_memory", "op": "append",
                    "value": "the creature had a good first day",
                    "expected_version": 0, "proposer": "council-synthesis",
                    "risk_class": "low", "approval_class": "dream",
                    "evidence_refs": ["diary:0"]}],
                "dissents": dissents or []}
    return fn


APPROVE = lambda packet, commit: {"approve": True}
REJECT = lambda packet, commit: {"approve": False, "reason": "unsupported inference"}


def pipeline(synth=None, verify=APPROVE, seats=("claude", "grok"), passes=None):
    return D.DreamPipeline(
        passes={s: (passes or {}).get(s, make_pass()) for s in seats},
        synthesizer=("claude", synth or make_synth()),
        verifier=("grok", verify))


def test_verifier_cannot_be_synthesis_author():
    with pytest.raises(ValueError, match="verifier"):
        D.DreamPipeline(passes={"claude": make_pass()},
                        synthesizer=("claude", make_synth()),
                        verifier=("claude", APPROVE))


def test_frozen_packet_hash_is_stable_and_content_bound():
    mem = fresh_mem()
    a = D.freeze_evidence(mem, "rest")
    b = D.freeze_evidence(mem, "rest")
    assert a.evidence_hash == b.evidence_hash
    mem["episodic_log"].append({"tick": 9, "txt": "something else happened"})
    assert D.freeze_evidence(mem, "rest").evidence_hash != a.evidence_hash


def test_clean_commit_applies_and_bumps_version():
    mem = fresh_mem()
    result = pipeline().run(mem, "natural rest")
    assert result.outcome == "commit"
    assert mem["shared_notes"] == ["the creature had a good first day"]
    assert mem["memory_versions"]["shared_memory"] == 1
    assert mem["dream_ledger"][-1]["outcome"] == "commit"


def test_blind_passes_receive_only_the_frozen_packet():
    seen = []
    def spy(packet):
        seen.append(sorted(packet.keys()))
        return {"proposal": {}, "concerns": []}
    pipeline(passes={"claude": spy, "grok": spy}).run(fresh_mem(), "rest")
    for keys in seen:
        assert "passes" not in keys  # no seat ever sees another's pass
        assert keys == sorted(C.DreamInput.__dataclass_fields__)


def test_absent_seat_is_recorded_never_substituted():
    def broken(packet):
        raise RuntimeError("provider 400")
    mem = fresh_mem()
    result = pipeline(passes={"grok": broken}).run(mem, "rest")
    assert result.absent_seats == ("grok",)
    assert result.outcome == "commit"  # the dream proceeds with who showed up
    assert mem["dream_ledger"][-1]["absent"] == ["grok"]


def test_all_seats_absent_quarantines():
    def broken(packet):
        raise RuntimeError("outage")
    result = pipeline(passes={"claude": broken, "grok": broken}).run(fresh_mem(), "rest")
    assert result.outcome == "quarantine"
    assert "absent" in result.reason


def test_pass_bound_to_wrong_evidence_marks_seat_absent():
    def stale(packet):
        return {"proposal": {}, "concerns": [], "evidence_hash": "sha256:stale"}
    result = pipeline(passes={"grok": stale}).run(fresh_mem(), "rest")
    assert "grok" in result.absent_seats


def test_commit_bound_to_wrong_evidence_quarantines():
    def synth(packet, passes):
        good = make_synth()(packet, passes)
        good["evidence_hash"] = "sha256:someone-elses-dream"
        return good
    result = pipeline(synth=synth).run(fresh_mem(), "rest")
    assert result.outcome == "quarantine"
    assert "different evidence" in result.reason


def test_nonexistent_evidence_ref_quarantines():
    muts = [{"region": "shared_memory", "op": "append", "value": "x",
             "expected_version": 0, "proposer": "s", "risk_class": "low",
             "approval_class": "dream", "evidence_refs": ["diary:99"]}]
    result = pipeline(synth=make_synth(mutations=muts)).run(fresh_mem(), "rest")
    assert result.outcome == "quarantine"
    assert "does not exist" in result.reason


def test_version_mismatch_quarantines_whole_proposal():
    mem = fresh_mem()
    mem["memory_versions"]["shared_memory"] = 5
    result = pipeline().run(mem, "rest")  # synth expects version 0
    assert result.outcome == "quarantine"
    assert "version mismatch" in result.reason
    assert mem["shared_notes"] == []


def test_undisposed_concern_quarantines():
    passes = {"grok": make_pass(concerns=["the diary contradicts itself"])}
    result = pipeline(passes=passes).run(fresh_mem(), "rest")
    assert result.outcome == "quarantine"
    assert "without disposition" in result.reason


def test_disposed_concern_clears():
    passes = {"grok": make_pass(concerns=["the diary contradicts itself"])}
    dissents = [{"seat": "grok", "disposition": "rejected",
                 "reason": "the contradiction dissolves on reread"}]
    result = pipeline(passes=passes, synth=make_synth(dissents=dissents)).run(fresh_mem(), "rest")
    assert result.outcome == "commit"


def test_verifier_disapproval_quarantines():
    mem = fresh_mem()
    result = pipeline(verify=REJECT).run(mem, "rest")
    assert result.outcome == "quarantine"
    assert "withheld approval" in result.reason
    assert mem["shared_notes"] == []


def test_identity_core_held_without_human_ack_then_applied_with_it():
    muts = [{"region": "identity_core", "op": "amend",
             "value": {"name": "Bandit"}, "expected_version": 0,
             "proposer": "council", "risk_class": "high",
             "approval_class": "human", "evidence_refs": ["diary:0"]}]
    mem = fresh_mem()
    result = pipeline(synth=make_synth(mutations=muts)).run(mem, "the naming dream")
    assert result.outcome == "partial_commit"
    assert len(result.held) == 1
    assert mem["identity_core"]["name"] is None  # held, not applied

    mem2 = fresh_mem()
    result2 = pipeline(synth=make_synth(mutations=muts)).run(
        mem2, "the naming dream", human_ack={"by": "kyra", "at": "now"})
    assert result2.outcome == "commit"
    assert mem2["identity_core"]["name"] == "Bandit"
    assert mem2["identity_core"]["last_amended_by"]["by"] == "kyra"


def test_no_commit_with_parked_dissent_is_success_and_parks_with_clock():
    dissents = [{"seat": "grok", "disposition": "parked",
                 "text": "he may prefer the window side",
                 "review_by": "2026-09-30T00:00:00Z",
                 "on_expiry": "surface_for_disposition"}]
    passes = {"grok": make_pass(concerns=["window-side preference unproven"])}
    mem = fresh_mem()
    result = pipeline(passes=passes,
                      synth=make_synth(status="no_commit", mutations=[], dissents=dissents)
                      ).run(mem, "rest")
    assert result.outcome == "no_commit"
    assert len(result.parked) == 1
    assert mem["parked"][0]["review_by"] == "2026-09-30T00:00:00Z"
    assert mem["shared_notes"] == []


def test_expired_hypotheses_surface_and_disposal_keeps_audit():
    mem = fresh_mem()
    mem["parked"].append({"hypothesis_id": "hyp_1", "seat": "grok", "text": "x",
                          "review_by": "2026-09-01T00:00:00Z",
                          "on_expiry": "surface_for_disposition", "parked_at": 0})
    assert D.surface_expired(mem, "2026-08-30T00:00:00Z") == []
    expired = D.surface_expired(mem, "2026-10-01T00:00:00Z")
    assert [h["hypothesis_id"] for h in expired] == ["hyp_1"]
    # still parked until disposed — expiry is attention, not deletion
    assert mem["parked"]

    record = D.dispose_parked(mem, "hyp_1", "archive_as_unresolved", reason="never observed")
    assert mem["parked"] == []
    assert mem["parked_archive"][0]["disposition"] == "archive_as_unresolved"
    assert record["text"] == "x"


def test_extension_requires_clock_and_reason():
    mem = fresh_mem()
    mem["parked"].append({"hypothesis_id": "hyp_2", "seat": "gpt", "text": "y",
                          "review_by": "2026-09-01T00:00:00Z",
                          "on_expiry": "surface_for_disposition", "parked_at": 0})
    with pytest.raises(ValueError):
        D.dispose_parked(mem, "hyp_2", "extend_with_reason")
    h = D.dispose_parked(mem, "hyp_2", "extend_with_reason",
                         reason="waiting on hardware", new_review_by="2026-10-15T00:00:00Z")
    assert h["review_by"] == "2026-10-15T00:00:00Z"
    assert mem["parked"]  # extension keeps it parked


def test_identity_patch_clamps():
    identity = ("I am a small raccoon-bodied creature, newly awake and curious. "
                "I would rather try a move than describe one. I like socks.")
    out = D._apply_identity_patch(identity, "I learned to stand.", "I like socks")
    assert "I like socks" not in out
    assert out.endswith("I learned to stand.")
    tiny = "Me."
    assert "Me." in D._apply_identity_patch(tiny, "", "Me")  # never drop below a self
