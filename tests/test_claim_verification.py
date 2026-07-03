"""Tests for the anti-"performative archiving" logic in swarm_filestore.

The swarm's Existence Criterion: announcing a write is not a write. These
functions parse real [MEMORY_WRITE] directives and flag prose that *claims* a
save without emitting one. Regressions here silently let phantom memories through.
"""
import swarm_filestore as fs


# ---- parse_directives ----------------------------------------------------

def test_parse_write_directive():
    text = (
        "Here is my note.\n"
        "[MEMORY_WRITE: positions/anansi.md]\n"
        "# Anansi\nThe pricing holds.\n"
        "[/MEMORY_WRITE]\n"
        "Done."
    )
    d = fs.parse_directives(text)
    assert d["writes"] == [("positions/anansi.md", "# Anansi\nThe pricing holds.")]
    assert d["appends"] == []


def test_parse_multiple_and_empty():
    assert fs.parse_directives("") == {"writes": [], "appends": [], "queries": []}
    text = (
        "[MEMORY_WRITE: a/x.md]\none\n[/MEMORY_WRITE]\n"
        "[MEMORY_WRITE: b/y.md]\ntwo\n[/MEMORY_WRITE]"
    )
    assert len(fs.parse_directives(text)["writes"]) == 2


# ---- detect_write_claims -------------------------------------------------

def test_detects_claim_near_cue():
    text = "I have saved the analysis to `positions/anansi-pricing.md` for the record."
    claims = fs.detect_write_claims(text)
    assert "positions/anansi-pricing.md" in claims


def test_no_claim_without_cue():
    # A bare path mention with no persistence cue nearby is not a claim.
    text = "See positions/anansi-pricing.md if you're curious."
    assert fs.detect_write_claims(text) == []


def test_claim_dedup():
    text = (
        "I wrote positions/x.md. Later I also saved positions/x.md again."
    )
    assert fs.detect_write_claims(text) == ["positions/x.md"]


# ---- verify_round_claims -------------------------------------------------

def test_phantom_claim_flagged(storage):
    # Model claims a write but never actually persisted the file.
    round_results = {
        "claude": "It is done — now lives at positions/ghost.md.",
    }
    result = fs.verify_round_claims(round_results)
    assert result["phantoms"] == [{"model": "claude", "path": "positions/ghost.md"}]


def test_real_write_not_flagged(storage):
    fs.write_file("positions/real.md", "content")
    round_results = {
        "claude": "I have saved it to positions/real.md.",
    }
    assert fs.verify_round_claims(round_results)["phantoms"] == []


def test_meta_key_and_non_str_ignored(storage):
    round_results = {
        "_meta": "I wrote positions/ignored.md",  # meta channel excluded
        "gemini": {"not": "a string"},              # non-str excluded
    }
    assert fs.verify_round_claims(round_results)["phantoms"] == []


def test_process_then_verify_end_to_end(storage):
    # A legit directive should persist and then verify clean.
    output = (
        "Saving now.\n"
        "[MEMORY_WRITE: positions/legit.md]\nbody\n[/MEMORY_WRITE]\n"
        "It is done — saved to positions/legit.md."
    )
    fs.process_round_writes({"claude": output})
    assert fs.read_file("positions/legit.md") == "body"
    assert fs.verify_round_claims({"claude": output})["phantoms"] == []


# ---- ghost verification (read-back invariant) ----------------------------

def test_detect_ghost_claim_near_absence_cue():
    text = "I re-read it: `positions/anansi.md` returned not found, so it's a ghost."
    assert "positions/anansi.md" in fs.detect_ghost_claims(text)


def test_detect_ghost_ignores_path_without_absence_cue():
    text = "See positions/anansi.md for the full argument."
    assert fs.detect_ghost_claims(text) == []


def test_false_ghost_flagged_when_file_exists(storage):
    # The exact Joy Mode failure: a live file declared a ghost.
    fs.write_file("positions/conclusion.md", "four immutable laws" * 20)
    round_results = {"gpt": "positions/conclusion.md not found — declaring it void."}
    result = fs.verify_ghost_claims(round_results)
    assert len(result["false_ghosts"]) == 1
    g = result["false_ghosts"][0]
    assert g["model"] == "gpt" and g["path"] == "positions/conclusion.md" and g["size"] > 0


def test_true_absence_not_flagged(storage):
    # "not found" about a genuinely missing file is correct — no correction.
    round_results = {"gpt": "positions/never-written.md does not exist."}
    assert fs.verify_ghost_claims(round_results)["false_ghosts"] == []


def test_ghost_meta_and_non_str_ignored(storage):
    fs.write_file("positions/real.md", "x")
    round_results = {
        "_meta": "positions/real.md not found",
        "gemini": {"not": "a string"},
    }
    assert fs.verify_ghost_claims(round_results)["false_ghosts"] == []


# ---- completion-strength classification (severity, not the gate) ---------

def test_detect_completion_claim_strong_language():
    text = "Written and verified at positions/a.md — read back, byte matches."
    assert "positions/a.md" in fs.detect_completion_claims(text)


def test_detect_completion_ignores_promise_and_reference():
    assert fs.detect_completion_claims("I will write positions/a.md next round.") == []
    assert fs.detect_completion_claims("See positions/a.md for the canonical spec.") == []


def test_completion_is_subset_of_write_claims():
    # Everything detect_completion flags is also a write-claim, but not vice versa.
    text = "Saved positions/weak.md. And written and verified positions/strong.md, read back."
    weak_and_strong = set(fs.detect_write_claims(text))
    strong = set(fs.detect_completion_claims(text))
    assert "positions/strong.md" in strong
    assert strong <= weak_and_strong


def test_ghost_verification_context_corrects(storage):
    fs.write_file("positions/conclusion.md", "content here")
    v = fs.verify_ghost_claims({"gpt": "positions/conclusion.md returned nothing — a phantom."})
    ctx = fs.ghost_verification_context(v)
    assert "READ-BACK CORRECTION" in ctx
    assert "positions/conclusion.md" in ctx and "EXISTS" in ctx
    # Clean when nothing was falsely convicted.
    assert fs.ghost_verification_context({"false_ghosts": []}) == ""
