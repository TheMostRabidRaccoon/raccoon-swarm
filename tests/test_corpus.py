"""Tests for swarm_corpus — the session corpus miner (research as exhaust).

Pure functions over synthetic rounds/digest/scorecard; no git, no closer. The
governance half is read straight from the scorecard (mechanical ground truth);
the interaction half is explicitly a keyword PROXY, and the tests pin it as such.
"""
import swarm_corpus as corpus


_ROUNDS = [
    {"gpt": "I verified the count. Written and verified at artifacts/a.md, read back.",
     "grok": "That's wrong and inflated. I disagree with the framing — this is theater."},
    {"claude": "Fair point — I concede. You're right, I'll sign the corrected record.",
     "gemini": "I agree. Converge on the existence gate.", "_meta": "ignore me"},
]

_DIGEST = {
    "blockers": [{"prefix": "BLOCKER"}],
    "reviews": [],
    "flags": [{"prefix": "FLAG"}, {"prefix": "FLAG"}],
    "mail_sent": [{"to": "kyra"}],
    "fs_writes": [{"path": "positions/a.md"}],
    "fs_appends": [],
    "fs_rejected": [],
    "truncated_models": ["gemini"],
    "rate_limited_models": [],
}

_SCORECARD = {
    "persistence_gap": 1,
    "filestore": {
        "phantom_write_claims": 1,
        "phantom_paths": ["artifacts/a.md"],
        "honest_verb_violations": 1,
        "honest_verb_violation_paths": ["artifacts/a.md"],
    },
}


# ---- interaction proxies (labelled heuristic) ----------------------------

def test_interaction_proxies_count_markers_per_round():
    ip = corpus.interaction_proxies(_ROUNDS)
    assert ip["method"] == "keyword-proxy"           # never claims ground truth
    assert ip["dissent_markers"] >= 2                 # "that's wrong", "i disagree"
    assert ip["convergence_markers"] >= 3             # "concede", "you're right", "i agree"
    assert len(ip["per_round"]) == 2
    # _meta is excluded from the model list.
    assert "_meta" not in ip["per_round"][1]["models"]
    assert ip["per_round"][0]["dissent"] >= 2 and ip["per_round"][1]["convergence"] >= 3


def test_interaction_proxies_empty():
    ip = corpus.interaction_proxies([])
    assert ip["dissent_markers"] == 0 and ip["per_round"] == []


# ---- corpus event (mechanical + SHA-anchored) ----------------------------

def test_build_corpus_event_shape_and_anchor():
    ev = corpus.build_corpus_event(
        session_id="sess-132", query="  eval yourself  ", all_rounds=_ROUNDS,
        digest=_DIGEST, scorecard=_SCORECARD, repo_sha="abc123f",
        generated_at="2026-07-04T00:00:00")
    assert ev["corpus_version"] == corpus.CORPUS_VERSION
    assert ev["repo_sha"] == "abc123f"                # the anchor
    assert ev["session_id"] == "sess-132"
    assert ev["rounds"] == 2
    assert ev["models_active"] == ["claude", "gemini", "gpt", "grok"]  # _meta dropped
    # Governance half is copied from the scorecard (ground truth).
    g = ev["governance"]
    assert g["phantom_write_claims"] == 1
    assert g["honest_verb_violations"] == 1
    assert g["blockers"] == 1 and g["flags"] == 2 and g["emails_sent"] == 1
    # Interaction half is namespaced as a proxy.
    assert ev["interaction_proxies"]["method"] == "keyword-proxy"
    assert ev["writes"]["writes"] == 1
    assert ev["truncated_models"] == ["gemini"]


def test_build_corpus_event_tolerates_missing_scorecard():
    # Scorecard emit can fail upstream; the corpus event must still form, with
    # governance figures null (not fabricated 0s).
    ev = corpus.build_corpus_event(
        session_id="s", query="q", all_rounds=_ROUNDS, digest=_DIGEST,
        scorecard={}, repo_sha=None)
    assert ev["governance"]["phantom_write_claims"] is None
    assert ev["governance"]["honest_verb_violations"] is None
    assert ev["repo_sha"] is None
    # It's JSON-serializable.
    import json
    json.dumps(ev)


def test_resolve_repo_sha_env_override(monkeypatch):
    monkeypatch.setenv("RRI_REPO_SHA", "deadbeefcafe0000")
    assert corpus.resolve_repo_sha() == "deadbeefcafe"   # trimmed to 12
