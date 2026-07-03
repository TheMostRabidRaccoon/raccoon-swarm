"""Unit tests for swarm_proposals — the Joy Mode tool-proposal handoff.

Pure-function coverage: parse a [TOOL_PROPOSAL] block, validate, queue through
the queued/→filed/→failed/ state machine, and format the GitHub issue. All
on-disk state uses the `storage` fixture (isolated tmp filestore). No network.
"""
import json

import pytest

import swarm_filestore as fs
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


# ---- parse ---------------------------------------------------------------

def test_parse_full_block():
    p = sp.parse_proposal(_FULL_BLOCK)
    assert p is not None
    assert p["name"] == "Word Counter"
    assert p["slug"] == "word-counter"
    assert p["description"] == "count words in a filestore doc"
    assert json.loads(p["json_schema"])["name"] == "word_counter"
    assert "no writes" in p["risk_notes"]
    assert "def test_word_counter" in p["test_stub"]


def test_parse_returns_none_without_block():
    assert sp.parse_proposal("no proposal here") is None
    assert sp.parse_proposal("") is None


def test_parse_returns_none_without_name():
    block = "[TOOL_PROPOSAL]\ndescription: nameless\n[/TOOL_PROPOSAL]"
    assert sp.parse_proposal(block) is None


def test_parse_preserves_raw_when_fields_sparse():
    block = "[TOOL_PROPOSAL]\nname: bare-tool\ndescription: just a description\n[/TOOL_PROPOSAL]"
    p = sp.parse_proposal(block)
    assert p["slug"] == "bare-tool"
    assert p["json_schema"] == "" and p["test_stub"] == ""
    assert "just a description" in p["raw"]


def test_parse_ignores_non_json_fence_for_schema():
    block = (
        "[TOOL_PROPOSAL]\nname: t\ndescription: d\n"
        "```python\ndef test_t(): assert True\n```\n[/TOOL_PROPOSAL]"
    )
    p = sp.parse_proposal(block)
    assert p["json_schema"] == ""          # the python fence is NOT taken as schema
    assert "def test_t" in p["test_stub"]


# ---- validate ------------------------------------------------------------

def test_validate_requires_name_and_substance():
    ok, _ = sp.validate_proposal({"slug": "t", "description": "d"})
    assert ok
    ok, err = sp.validate_proposal({"slug": "", "description": "d"})
    assert not ok and "name" in err
    ok, err = sp.validate_proposal({"slug": "t", "description": "", "json_schema": ""})
    assert not ok and ("schema" in err or "description" in err)


# ---- queue + state machine ----------------------------------------------

def test_queue_and_list(storage):
    p = sp.parse_proposal(_FULL_BLOCK)
    res = sp.queue_proposal(p, source="joy", date_str="2026-07-05")
    assert res["ok"] is True
    pid = res["proposal_id"]
    assert "word-counter" in pid
    assert sp.list_state(sp.QUEUED)[0]["proposal_id"] == pid

    record = sp.read_proposal(sp.QUEUED, pid)
    assert record["source"] == "joy" and record["date"] == "2026-07-05"
    assert record["proposal_version"] == sp.PROPOSAL_VERSION


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

def test_format_issue_has_gate_and_sections():
    p = sp.parse_proposal(_FULL_BLOCK)
    issue = sp.format_issue({**p, "source": "joy", "date": "2026-07-05"})
    assert issue["title"] == "[tool-proposal] Word Counter"
    body = issue["body"]
    assert "AUTONOMY GATE" in body                 # the merge gate is loud
    assert "do NOT merge" in body
    assert "## Proposed tool schema" in body
    assert "word_counter" in body
    assert "## Risk notes" in body
    assert "## Test stub" in body
    assert "Checklist before promotion" in body


def test_format_issue_falls_back_to_raw():
    # No parseable schema/test -> the raw block is embedded so nothing is lost.
    p = sp.parse_proposal("[TOOL_PROPOSAL]\nname: bare\ndescription: d\n[/TOOL_PROPOSAL]")
    body = sp.format_issue(p)["body"]
    assert "## Raw proposal" in body
    assert "AUTONOMY GATE" in body
