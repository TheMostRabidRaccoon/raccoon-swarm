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
