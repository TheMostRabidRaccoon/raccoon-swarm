"""Tests for the swarm_dispatch filesystem state machine.

The filesystem is the source of truth for the video pipeline handoff, so the
guarantees that matter are: bad payloads are rejected, ids can't escape the
dispatch dir, and state transitions are atomic and only valid when the source
file actually exists.
"""
import swarm_dispatch as dp


def _valid_payload():
    return {
        "dispatch_version": "1",
        "submitted_at": "2026-07-01T12:00:00",
        "submitted_by": "swarm-session-62/claude/phase-4",
        "script": {"project_slug": "pigeons-ep2", "panels": [{"index": 0}]},
    }


# ---- validate_payload ----------------------------------------------------

def test_valid_payload_accepted():
    ok, err = dp.validate_payload(_valid_payload())
    assert ok and err is None


def test_missing_fields_rejected():
    p = _valid_payload()
    del p["script"]
    ok, err = dp.validate_payload(p)
    assert not ok and "script" in err


def test_bad_version_rejected():
    p = _valid_payload()
    p["dispatch_version"] = "9"
    ok, err = dp.validate_payload(p)
    assert not ok and "dispatch_version" in err


def test_empty_panels_rejected():
    p = _valid_payload()
    p["script"]["panels"] = []
    ok, err = dp.validate_payload(p)
    assert not ok and "panels" in err


def test_panel_without_index_rejected():
    p = _valid_payload()
    p["script"]["panels"] = [{"caption": "no index here"}]
    ok, err = dp.validate_payload(p)
    assert not ok and "index" in err


# ---- id safety -----------------------------------------------------------

def test_payload_path_rejects_unsafe_id(storage):
    assert dp._payload_path("queued", "../../etc/passwd") is None
    assert dp._payload_path("queued", "a/b") is None
    assert dp._payload_path("bogus_state", "goodid") is None


def test_safe_id_sanitizes_submitter(storage):
    # Slashes and unsafe chars must be scrubbed out of the generated id.
    sid = dp._safe_id("swarm/../../evil", "ep/2")
    assert "/" not in sid and ".." not in sid


# ---- write + transition round trip --------------------------------------

def test_write_payload_lands_in_queued(storage):
    res = dp.write_payload(_valid_payload(), submitted_by="tester")
    assert res["ok"], res
    did = res["dispatch_id"]
    assert dp.read_payload("queued", did) is not None


def test_write_payload_autofills(storage):
    # A terse payload (no version/submitted_at) should be auto-completed.
    terse = {"script": {"panels": [{"index": 0}]}}
    res = dp.write_payload(terse, submitted_by="tester")
    assert res["ok"], res
    stored = dp.read_payload("queued", res["dispatch_id"])
    assert stored["dispatch_version"] == "1"
    assert stored["submitted_by"] == "tester"


def test_write_payload_rejects_invalid(storage):
    res = dp.write_payload({"script": {"panels": []}})
    assert not res["ok"] and "error" in res


def test_full_state_machine(storage):
    did = dp.write_payload(_valid_payload(), submitted_by="tester")["dispatch_id"]
    # queued -> processing -> done
    assert dp.transition(did, "queued", "processing") is not None
    assert dp.read_payload("queued", did) is None
    assert dp.read_payload("processing", did) is not None
    assert dp.transition(did, "processing", "done") is not None
    assert dp.read_payload("done", did) is not None


def test_transition_missing_source_returns_none(storage):
    assert dp.transition("does-not-exist", "queued", "processing") is None


def test_transition_invalid_state_returns_none(storage):
    did = dp.write_payload(_valid_payload(), submitted_by="tester")["dispatch_id"]
    assert dp.transition(did, "queued", "nirvana") is None


def test_status_counts(storage):
    dp.write_payload(_valid_payload(), submitted_by="tester")
    st = dp.status()
    assert st["counts"]["queued"] >= 1
    assert set(st["counts"]) == {"queued", "processing", "done", "failed"}
