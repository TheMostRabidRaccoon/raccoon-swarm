"""Tests for the session scorecard (swarm_closer) — the measurement arc's v0.

build_scorecard is a pure mapping over a digest; count_phantom_claims reuses the
#66 phantom-write detector against a real filestore. Both stdlib-only (no SMTP,
no model stack), so they run in CI.
"""
import json

import swarm_closer as closer
import swarm_filestore as fs


# ---- build_scorecard (pure) ----------------------------------------------

def _digest(**over):
    base = {
        "session_id": "sess-1",
        "query": "  what is the anansi pricing model?  ",
        "rounds": [
            {"round": 1, "models": ["claude", "gpt"]},
            {"round": 2, "models": ["gpt", "grok"]},
        ],
        "duration_sec": 42.5,
        "fs_writes": [{"path": "positions/a.md"}],
        "fs_appends": [],
        "fs_rejected": [{"path": "bad/../x.md"}],
        "mail_sent": [{"to": "x"}],
        "mail_rejected": [],
        "blockers": [{"prefix": "BLOCKER"}],
        "reviews": [],
        "flags": [{"prefix": "FLAG"}, {"prefix": "FLAG"}],
        "truncated_models": ["gemini"],
        "rate_limited_models": [],
        "audit_counts": {"decisions": 3},
    }
    base.update(over)
    return base


def test_scorecard_counts_and_shape():
    sc = closer.build_scorecard(_digest(), phantom_write_claims=2)
    assert sc["scorecard_version"] == closer.SCORECARD_VERSION
    assert sc["session_id"] == "sess-1"
    assert sc["rounds"] == 2
    assert sc["models_active"] == ["claude", "gpt", "grok"]  # sorted union across rounds
    assert sc["duration_sec"] == 42.5
    assert sc["filestore"] == {"writes": 1, "appends": 0, "rejected": 1, "phantom_write_claims": 2}
    assert sc["persistence_gap"] == 2
    assert sc["mail"] == {"sent": 1, "rejected": 0}
    assert sc["synthesis_directives"] == {"blockers": 1, "reviews": 0, "flags": 2}
    assert sc["truncated_models"] == ["gemini"]
    assert sc["audit_counts"] == {"decisions": 3}


def test_scorecard_query_truncated_and_trimmed():
    sc = closer.build_scorecard(_digest(query="x" * 500), phantom_write_claims=0)
    assert len(sc["query"]) == 200


def test_scorecard_has_no_selfgraded_fields():
    # Judgment fields are excluded by design — mechanical only.
    sc = closer.build_scorecard(_digest(), phantom_write_claims=0)
    for banned in ("usefulness_score", "quality", "disagreement_quality", "convergence_quality"):
        assert banned not in sc
    # Deferred fields are present-but-null, not silently missing.
    assert sc["cost_usd"] is None
    assert sc["tool_calls"] is None
    assert sc["citations_verified"] is None
    assert "deferred_fields" in sc


def test_scorecard_serializes_to_json():
    sc = closer.build_scorecard(_digest(), phantom_write_claims=1)
    assert json.loads(json.dumps(sc))["persistence_gap"] == 1


def test_empty_digest_is_safe():
    sc = closer.build_scorecard({}, phantom_write_claims=0)
    assert sc["rounds"] == 0 and sc["models_active"] == []
    assert sc["persistence_gap"] == 0


# ---- count_phantom_claims (uses the real filestore) ----------------------

def test_phantom_claims_counts_only_unpersisted(storage):
    # One real file, one phantom path claimed in the synthesis.
    fs.write_file("positions/real.md", "content")
    synthesis = (
        "I saved the analysis to positions/real.md, and it is done — "
        "now lives at positions/ghost.md."
    )
    assert closer.count_phantom_claims([], synthesis) == 1  # only ghost is phantom


def test_phantom_claims_dedup_across_rounds_and_synthesis(storage):
    # Same phantom path claimed in a round AND the synthesis counts once.
    all_rounds = [{"claude": "I wrote positions/ghost.md"}]
    synthesis = "As saved, positions/ghost.md now exists."
    assert closer.count_phantom_claims(all_rounds, synthesis) == 1


def test_phantom_claims_zero_when_all_persisted(storage):
    fs.write_file("positions/kept.md", "x")
    assert closer.count_phantom_claims([], "saved to positions/kept.md") == 0
