"""Unit tests for swarm_proposals — generic persistence-to-review handoff.

Covers backward-compatible [TOOL_PROPOSAL], generic [CHANGE_PROPOSAL], queue
state, round-wide capture, and issue formatting. No network.
"""
import json

import swarm_proposals as sp


_FULL_BLOCK = (
    "prelude text\n"
    "[TOOL_PROPOSAL]\n"
    "name: Word Counter\n"
    "description: count words in a filestore doc\n"
    "```json\n"
    '{"name": "word_counter", "description": "count words", "input_schema": {"type": "object"}}\n'
    "```\n"
    "risks: reads only inside the sandbox; no writes; bounded output.\n"
    "```python\n"
    "def test_word_counter():\n    assert True\n"
    "```\n"
    "[/TOOL_PROPOSAL]\n"
    "trailing text"
)

_CHANGE_BLOCK = """[CHANGE_PROPOSAL]
name: Roles as attention, not departments
kind: architecture
summary: Remove jurisdictional role semantics from the active swarm.
observation: The prompt says peer network but runtime language still assigns offices.
evidence:
source:swarm_runtime.py:1200 Scribe/Editor/Postmaster language
source:swarm_ecology.py:1 active peer ontology
proposed_change: Make roles attentional priors and move workflow ownership to artifact state.
expected_effect: More cross-specialty initiative without weakening hard safety gates.
validation: Re-run identical prompts and measure jurisdiction/delegation language before/after.
risks: Shared action space can create collisions; preserve mechanical provenance and review routes.
source_sha: abc123
[/CHANGE_PROPOSAL]"""


# ---- parse ---------------------------------------------------------------

def test_parse_full_tool_block():
    p = sp.parse_proposal(_FULL_BLOCK)
    assert p is not None
    assert p["proposal_type"] == "tool"
    assert p["name"] == "Word Counter"
    assert p["slug"] == "word-counter"
    assert p["description"] == "count words in a filestore doc"
    assert json.loads(p["json_schema"])["name"] == "word_counter"
    assert "no writes" in p["risk_notes"]
    assert "def test_word_counter" in p["test_stub"]


def test_parse_change_block():
    p = sp.parse_proposal(_CHANGE_BLOCK)
    assert p is not None
    assert p["proposal_type"] == "change"
    assert p["change_kind"] == "architecture"
    assert p["name"] == "Roles as attention, not departments"
    assert "jurisdictional role semantics" in p["summary"]
    assert "Scribe/Editor/Postmaster" in p["evidence"]
    assert "artifact state" in p["proposed_change"]
    assert p["source_sha"] == "abc123"


def test_parse_returns_none_without_block():
    assert sp.parse_proposal("no proposal here") is None
    assert sp.parse_proposal("") is None


def test_parse_returns_none_without_name():
    block = "[TOOL_PROPOSAL]\ndescription: nameless\n[/TOOL_PROPOSAL]"
    assert sp.parse_proposal(block) is None


def test_parse_preserves_raw_when_tool_fields_sparse():
    block = "[TOOL_PROPOSAL]\nname: bare-tool\ndescription: just a description\n[/TOOL_PROPOSAL]"
    p = sp.parse_proposal(block)
    assert p["slug"] == "bare-tool"
    assert p["json_schema"] == "" and p["test_stub"] == ""
    assert "just a description" in p["raw"]


def test_parse_proposals_preserves_cross_type_order():
    text = f"{_CHANGE_BLOCK}\ninterlude\n{_FULL_BLOCK}"
    parsed = sp.parse_proposals(text)
    assert [p["proposal_type"] for p in parsed] == ["change", "tool"]


# ---- validate ------------------------------------------------------------

def test_validate_tool_requires_name_and_substance():
    ok, _ = sp.validate_proposal({"slug": "t", "description": "d"})
    assert ok  # v1 records with no proposal_type remain tool-compatible
    ok, err = sp.validate_proposal({"slug": "", "description": "d"})
    assert not ok and "name" in err
    ok, err = sp.validate_proposal({"slug": "t", "description": "", "json_schema": ""})
    assert not ok and ("schema" in err or "description" in err)


def test_validate_change_requires_summary_and_actual_change():
    base = {"proposal_type": "change", "slug": "x", "summary": "why", "proposed_change": "do x"}
    assert sp.validate_proposal(base)[0] is True
    bad = dict(base, summary="")
    assert sp.validate_proposal(bad)[0] is False
    bad = dict(base, proposed_change="")
    assert sp.validate_proposal(bad)[0] is False


# ---- queue + state machine ----------------------------------------------

def test_queue_and_list_tool(storage):
    p = sp.parse_proposal(_FULL_BLOCK)
    res = sp.queue_proposal(p, source="joy", date_str="2026-07-05")
    assert res["ok"] is True
    pid = res["proposal_id"]
    assert "tool_word-counter" in pid
    assert sp.list_state(sp.QUEUED)[0]["proposal_id"] == pid

    record = sp.read_proposal(sp.QUEUED, pid)
    assert record["source"] == "joy" and record["date"] == "2026-07-05"
    assert record["proposal_version"] == sp.PROPOSAL_VERSION
    assert record["proposal_type"] == "tool"


def test_queue_change_direct_adapter(storage):
    res = sp.queue_change(
        name="Source self-observation",
        summary="Expose deployed source read-only.",
        proposed_change="Add source_status/read/search.",
        observation="The swarm currently infers its own source from stale summaries.",
        evidence="source_sha=abc",
        validation="Read active role prompt and verify exact lines.",
        source_sha="abc",
        source="session:test",
        date_str="2026-08-16",
    )
    assert res["ok"] is True
    assert "change_source-self-observation" in res["proposal_id"]
    rec = sp.read_proposal(sp.QUEUED, res["proposal_id"])
    assert rec["proposal_type"] == "change"
    assert rec["source_sha"] == "abc"


def test_queue_rejects_invalid(storage):
    res = sp.queue_proposal({"slug": "", "description": ""}, source="joy")
    assert res["ok"] is False


def test_transition_queued_to_filed(storage):
    pid = sp.queue_proposal(sp.parse_proposal(_FULL_BLOCK), date_str="2026-07-05")["proposal_id"]
    dst = sp.transition(pid, sp.QUEUED, sp.FILED)
    assert dst is not None
    assert sp.list_state(sp.QUEUED) == []
    assert sp.list_state(sp.FILED)[0]["proposal_id"] == pid


def test_transition_missing_returns_none(storage):
    assert sp.transition("nope", sp.QUEUED, sp.FILED) is None


def test_transition_rejects_bad_state(storage):
    pid = sp.queue_proposal(sp.parse_proposal(_FULL_BLOCK), date_str="2026-07-05")["proposal_id"]
    assert sp.transition(pid, sp.QUEUED, "bogus") is None


def test_status_counts(storage):
    sp.queue_proposal(sp.parse_proposal(_FULL_BLOCK), date_str="2026-07-05")
    st = sp.status()
    assert st["counts"][sp.QUEUED] == 1 and st["counts"][sp.FILED] == 0


# ---- format issue --------------------------------------------------------

def test_format_tool_issue_is_handoff_not_completion_claim():
    p = sp.parse_proposal(_FULL_BLOCK)
    issue = sp.format_issue({**p, "source": "joy", "date": "2026-07-05"})
    assert issue["title"] == "[tool-proposal] Word Counter"
    body = issue["body"]
    assert "REVIEW HANDOFF" in body
    assert "proposal, not deployed state" in body
    assert "## Proposed tool schema" in body
    assert "word_counter" in body
    assert "## Risk notes" in body
    assert "## Test stub" in body
    assert "Behaviorally verified" in body


def test_format_change_issue_carries_source_evidence_and_operationalization_states():
    p = sp.parse_proposal(_CHANGE_BLOCK)
    issue = sp.format_issue({**p, "source": "session:test", "date": "2026-08-16"})
    assert issue["title"] == "[change-proposal:architecture] Roles as attention, not departments"
    body = issue["body"]
    assert "Source observed:** `abc123`" in body
    assert "## Observation / problem" in body
    assert "## Evidence" in body
    assert "## Proposed change" in body
    assert "## Expected behavioral effect" in body
    assert "## Validation / falsification" in body
    assert "Integrated / deployed" in body
    assert "Behaviorally verified" in body


def test_format_tool_issue_falls_back_to_raw():
    p = sp.parse_proposal("[TOOL_PROPOSAL]\nname: bare\ndescription: d\n[/TOOL_PROPOSAL]")
    body = sp.format_issue(p)["body"]
    assert "## Raw proposal" in body
    assert "REVIEW HANDOFF" in body


# ---- process_round_proposals — any-session bridge ------------------------

_BLOCK_B = """[TOOL_PROPOSAL]
name: Path Verifier
description: batch existence checks for filestore paths
[/TOOL_PROPOSAL]"""


def test_round_proposals_queued_from_any_seat(storage):
    round_results = {
        "claude": f"Some deliberation.\n{_FULL_BLOCK}\nMore text.",
        "gpt": "no proposal here",
        "_meta": {"round": 1},
    }
    summary = sp.process_round_proposals(round_results, source="session:test123")
    assert len(summary["queued"]) == 1
    assert summary["queued"][0]["model"] == "claude"
    assert summary["queued"][0]["proposal_type"] == "tool"
    pid = summary["queued"][0]["proposal_id"]
    rec = sp.read_proposal(sp.QUEUED, pid)
    assert rec["source"] == "session:test123"


def test_round_bridge_queues_generic_change_without_new_pipeline(storage):
    summary = sp.process_round_proposals({"grok": _CHANGE_BLOCK}, source="session:self-inspect")
    assert len(summary["queued"]) == 1
    queued = summary["queued"][0]
    assert queued["proposal_type"] == "change"
    rec = sp.read_proposal(sp.QUEUED, queued["proposal_id"])
    assert rec["change_kind"] == "architecture"
    assert "attentional priors" in rec["proposed_change"]


def test_round_proposals_multiple_blocks_one_output(storage):
    round_results = {"gemini": f"{_FULL_BLOCK}\n\n{_CHANGE_BLOCK}\n\n{_BLOCK_B}"}
    summary = sp.process_round_proposals(round_results, source="session:x")
    slugs = {qd["slug"] for qd in summary["queued"]}
    assert slugs == {"word-counter", "roles-as-attention-not-departments", "path-verifier"}


def test_round_proposals_dedupes_echoed_slug(storage):
    round_results = {"claude": _FULL_BLOCK, "grok": _FULL_BLOCK}
    summary = sp.process_round_proposals(round_results, source="session:x")
    assert len(summary["queued"]) == 1
    assert len(summary["skipped_duplicates"]) == 1


def test_round_proposals_invalid_block_rejected_not_raised(storage):
    bad = "[TOOL_PROPOSAL]\nname: Bare Name Only\n[/TOOL_PROPOSAL]"
    summary = sp.process_round_proposals({"grok": bad}, source="session:x")
    assert summary["queued"] == []
    assert len(summary["rejected"]) == 1
    assert summary["rejected"][0]["error"]


def test_round_proposals_no_blocks_is_noop(storage):
    summary = sp.process_round_proposals({"claude": "just words"}, source="s")
    assert summary == {"queued": [], "rejected": [], "skipped_duplicates": []}
