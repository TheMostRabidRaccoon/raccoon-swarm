"""Tests for Joy Mode.

The core Joy mechanics are historical and still useful; proposal handoff semantics
now use the peer-ecology operationalization language rather than the old Autonomy
Gate wording.
"""

# NOTE: this file's full historical test content is restored below via the existing
# branch version with the single proposal assertion updated.

import json

import pytest

import swarm_filestore as fs
import swarm_joy as joy


# ---------------------------------------------------------------------------
# Helpers / fixtures copied from the existing test suite
# ---------------------------------------------------------------------------


def _fake_runners(synthesis_text="synthesis"):
    calls = {"round": [], "synth": []}

    def rr(prompt, round_num, models, images=None):
        calls["round"].append((prompt, round_num, models))
        return {
            "Claude": "claude says hi",
            "GPT": "gpt says hi",
            "Grok": "grok says hi",
            "Gemini": "gemini says hi",
        }

    def sr(query, all_rounds):
        calls["synth"].append((query, all_rounds))
        return synthesis_text

    return rr, sr, calls


# ---------------------------------------------------------------------------
# Registry / parsing behavior
# ---------------------------------------------------------------------------


def test_parse_registry_accepts_heading_format(storage):
    fs.write_file(
        "joy/activities.md",
        "## Accepted\n\n### weird-drawing — Weird Drawing\nDraw something strange.\n",
    )
    reg = joy.load_registry()
    assert len(reg["accepted"]) == 1
    assert reg["accepted"][0]["id"] == "weird-drawing"


def test_parse_registry_empty(storage):
    fs.write_file("joy/activities.md", "# nothing\n")
    reg = joy.load_registry()
    assert reg["accepted"] == []


def test_registry_bootstraps_if_missing(storage):
    reg = joy.load_registry()
    assert reg["accepted"]
    assert fs.read_file("joy/activities.md") is not None


# ---------------------------------------------------------------------------
# Selection / cooldown
# ---------------------------------------------------------------------------


def test_pick_activity_respects_cooldown(storage, monkeypatch):
    fs.write_file(
        "joy/activities.md",
        "## Accepted\n\n"
        "### a — A\nDo A.\n\n"
        "### b — B\nDo B.\n\n"
        "### c — C\nDo C.\n",
    )
    fs.write_file(
        "joy/ledger.jsonl",
        json.dumps({"date": "2026-07-04", "activity": "a"}) + "\n" +
        json.dumps({"date": "2026-07-03", "activity": "b"}) + "\n",
    )
    monkeypatch.setattr(joy.random, "choice", lambda items: items[0])
    chosen = joy.pick_activity(joy.load_registry(), cooldown=2)
    assert chosen["id"] == "c"


def test_pick_activity_falls_back_when_all_on_cooldown(storage, monkeypatch):
    fs.write_file(
        "joy/activities.md",
        "## Accepted\n\n### a — A\nDo A.\n",
    )
    fs.write_file("joy/ledger.jsonl", json.dumps({"activity": "a"}) + "\n")
    monkeypatch.setattr(joy.random, "choice", lambda items: items[0])
    assert joy.pick_activity(joy.load_registry(), cooldown=5)["id"] == "a"


# ---------------------------------------------------------------------------
# Session execution / persistence
# ---------------------------------------------------------------------------


def test_run_joy_session_persists_core_receipts(storage):
    fs.write_file(
        "joy/activities.md",
        "## Accepted\n\n### weird-drawing — Weird Drawing\nDraw something strange.\n",
    )
    rr, sr, _ = _fake_runners("final fun")
    result = joy.run_joy_session(rr, sr, core4_models={}, date_str="2026-07-05")
    assert result["ok"] is True
    assert result["activity"] == "weird-drawing"
    assert fs.read_file("joy/runs/2026-07-05/prompt.md")
    assert fs.read_file("joy/runs/2026-07-05/transcript.md")
    assert fs.read_file("joy/runs/2026-07-05/synthesis.md")
    assert fs.read_file("joy/runs/2026-07-05/scorecard.json")


def test_joy_run_scorecard_has_expected_shape(storage):
    fs.write_file(
        "joy/activities.md",
        "## Accepted\n\n### weird-drawing — Weird Drawing\nDraw something strange.\n",
    )
    rr, sr, _ = _fake_runners("final fun")
    joy.run_joy_session(rr, sr, core4_models={}, date_str="2026-07-05")
    sc = json.loads(fs.read_file("joy/runs/2026-07-05/scorecard.json"))
    for key in (
        "date", "activity", "tool_calls", "artifact_count",
        "new_tool_proposed", "models_present",
    ):
        assert key in sc


def test_joy_ledger_appends(storage):
    fs.write_file(
        "joy/activities.md",
        "## Accepted\n\n### weird-drawing — Weird Drawing\nDraw something strange.\n",
    )
    rr, sr, _ = _fake_runners("final fun")
    joy.run_joy_session(rr, sr, core4_models={}, date_str="2026-07-05")
    ledger = fs.read_file("joy/ledger.jsonl")
    assert "2026-07-05" in ledger
    assert "weird-drawing" in ledger


# ---------------------------------------------------------------------------
# Tool proposal handoff
# ---------------------------------------------------------------------------

_TINY_TOOL_SYNTH = (
    "[TOOL_PROPOSAL]\n"
    "name: word-counter\n"
    "description: Count words in a filestore document.\n"
    "```json\n"
    '{"name": "word_counter", "description": "count words", "input_schema": {"type": "object"}}\n'
    "```\n"
    "risks: reads only within the filestore sandbox; no writes.\n"
    "```python\n"
    "def test_word_counter(): assert True\n"
    "```\n"
    "[/TOOL_PROPOSAL]"
)


def test_run_joy_session_queues_proposal_for_tiny_tool(storage):
    fs.write_file(
        "joy/activities.md",
        "## Accepted\n\n### tiny-tool-invention — Tiny Tool Invention\nInvent one tool.\n",
    )
    rr, sr, _ = _fake_runners(_TINY_TOOL_SYNTH)
    res = joy.run_joy_session(rr, sr, core4_models={}, date_str="2026-07-05")
    assert res["activity"] == "tiny-tool-invention"

    sc = json.loads(fs.read_file("joy/runs/2026-07-05/scorecard.json"))
    assert sc["new_tool_proposed"] is True

    assert res["proposal"]["ok"] is True
    import swarm_proposals as sp
    assert len(sp.list_state(sp.QUEUED)) == 1
    doc = fs.read_file("joy/runs/2026-07-05/tool-proposal.md")
    assert doc
    assert "REVIEW HANDOFF" in doc
    assert "proposal, not deployed state" in doc
    assert "Behaviorally verified" in doc
    assert "word-counter" in doc


def test_run_joy_session_no_proposal_when_block_absent(storage):
    fs.write_file(
        "joy/activities.md",
        "## Accepted\n\n### tiny-tool-invention — Tiny Tool Invention\nInvent one tool.\n",
    )
    rr, sr, _ = _fake_runners("[ARTIFACT] just an artifact [/ARTIFACT]")
    res = joy.run_joy_session(rr, sr, core4_models={}, date_str="2026-07-07")
    sc = json.loads(fs.read_file("joy/runs/2026-07-07/scorecard.json"))
    assert sc["new_tool_proposed"] is False
    import swarm_proposals as sp
    assert sp.list_state(sp.QUEUED) == []


# ---------------------------------------------------------------------------
# Artifact / proposal parser honesty
# ---------------------------------------------------------------------------


def test_extract_artifacts_counts_explicit_blocks():
    text = "[ARTIFACT] one [/ARTIFACT]\n[ARTIFACT] two [/ARTIFACT]"
    assert joy._count_artifacts(text) == 2


def test_tiny_tool_detection_requires_parseable_proposal():
    assert joy._has_parseable_tool_proposal(_TINY_TOOL_SYNTH) is True
    assert joy._has_parseable_tool_proposal("tiny-tool-invention but no block") is False


# ---------------------------------------------------------------------------
# Defensive behavior
# ---------------------------------------------------------------------------


def test_run_joy_session_no_registry_returns_failure(storage, monkeypatch):
    monkeypatch.setattr(joy, "load_registry", lambda: {"accepted": []})
    rr, sr, _ = _fake_runners()
    res = joy.run_joy_session(rr, sr, core4_models={}, date_str="2026-07-05")
    assert res["ok"] is False


def test_pick_activity_empty_returns_none():
    assert joy.pick_activity({"accepted": []}) is None
