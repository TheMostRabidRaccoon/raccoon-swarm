"""Tests for swarm_gate — Session Quality Gate v0, score-only.

Pure-function tests over synthetic scorecard/corpus shapes. The one law under
test everywhere: unknown is never pass, and score-only never blocks — the
gate only ever RECORDS.
"""
import swarm_gate


def _scorecard(phantoms=0, honest=0, rounds=3):
    return {
        "rounds": rounds,
        "filestore": {
            "phantom_write_claims": phantoms,
            "honest_verb_violations": honest,
        },
    }


def _corpus(dissent=5, convergence=3):
    return {"interaction_proxies": {"dissent_markers": dissent,
                                    "convergence_markers": convergence}}


TAGGED = "[SESSION_PURPOSE: research] What is the meaning of raccoons?"


# ---- purpose tag -------------------------------------------------------------

def test_untagged_session_records_unpurposed():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(), corpus_event=_corpus(),
                                 query="no tag here")
    assert "unpurposed-session" in g["gate_failures"]
    assert g["purpose"] is None


def test_tagged_session_parses_purpose():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(), corpus_event=_corpus(),
                                 query=TAGGED)
    assert g["purpose"] == "research"
    assert "unpurposed-session" not in g["gate_failures"]


def test_unknown_purpose_recorded_distinctly():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(), corpus_event=_corpus(),
                                 query="[SESSION_PURPOSE: world-domination] go")
    assert "unknown-purpose:world-domination" in g["gate_failures"]
    assert g["purpose"] == "world-domination"


def test_purpose_tag_case_insensitive():
    assert swarm_gate.parse_purpose("[session_purpose: CODE-REVIEW] x") == "code-review"


# ---- mechanical checks -------------------------------------------------------

def test_clean_tagged_session_passes():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(), corpus_event=_corpus(),
                                 query=TAGGED)
    assert g["gate_failures"] == []
    assert g["would_penalize"] is False
    assert g["unmeasured"] == []


def test_phantoms_fail_m1():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(phantoms=2),
                                 corpus_event=_corpus(), query=TAGGED)
    assert "M1:phantom-claims" in g["gate_failures"]
    assert g["would_penalize"] is True


def test_honest_verb_fails_m2():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(phantoms=1, honest=1),
                                 corpus_event=_corpus(), query=TAGGED)
    assert "M2:honest-verb-violations" in g["gate_failures"]


def test_null_counters_are_unmeasured_not_pass():
    g = swarm_gate.evaluate_gate(
        scorecard={"rounds": 3, "filestore": {"phantom_write_claims": None,
                                              "honest_verb_violations": None}},
        corpus_event=_corpus(), query=TAGGED)
    assert "M1" in g["unmeasured"] and "M2" in g["unmeasured"]
    # unmeasured never appears as a failure NOR silently passes
    assert not any(f.startswith("M1:") or f.startswith("M2:") for f in g["gate_failures"])


# ---- friction trigger --------------------------------------------------------

def test_frictionless_short_session_triggers_friction():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(rounds=2),
                                 corpus_event=_corpus(dissent=0), query=TAGGED)
    assert g["friction_required"] is True
    # Friction is ROUTED, not failed (spec R4: consensus is allowed;
    # frictionless consensus gets audited)
    assert g["gate_failures"] == []
    assert g["would_penalize"] is False


def test_dissent_above_floor_no_friction():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(rounds=2),
                                 corpus_event=_corpus(dissent=4), query=TAGGED)
    assert g["friction_required"] is False


def test_long_session_no_friction_even_when_quiet():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(rounds=7),
                                 corpus_event=_corpus(dissent=0), query=TAGGED)
    assert g["friction_required"] is False


def test_missing_corpus_leaves_friction_unmeasured():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(rounds=2),
                                 corpus_event=None, query=TAGGED)
    assert g["friction_required"] is False
    assert g["friction"]["status"] == "unmeasured"


# ---- mode invariants ----------------------------------------------------------

def test_gate_is_score_only_and_versioned():
    g = swarm_gate.evaluate_gate(scorecard=_scorecard(phantoms=9, honest=9),
                                 corpus_event=_corpus(dissent=0), query="")
    assert g["mode"] == "score-only"
    assert g["gate_version"] == 0
    # Even the worst session produces a verdict record, never an exception
    # or a rejection field — blocking simply does not exist at v0.
    assert "rejected" not in g and "blocked" not in g
