"""Tests for swarm_memory — the cross-session JSON state layer.

Covers the three defects the extraction fixed:
1. pursuits were wholesale-replaced (silent memory decay),
2. question resolution never fired (exact question-text vs topic-string match),
3. superseded positions were still injected by recency.

Isolation: swarm_memory.memory_file() resolves from RRI_STORAGE_DIR at call
time (same pattern as swarm_filestore), so the shared `storage` fixture from
conftest.py is enough. No server import — stdlib-only, CI-safe.
"""
import json

import pytest

import swarm_memory


@pytest.fixture
def mem_env(storage, monkeypatch):
    """Isolated memory file + no seed bootstrap (tests control initial state)."""
    monkeypatch.setattr(swarm_memory, "MEMORY_SEED_FILE", storage / "no-such-seed.json")
    return storage


def _base_memory(**overrides):
    mem = swarm_memory.empty_memory()
    mem["session_count"] = 1  # so format_memory_context doesn't early-out
    mem.update(overrides)
    return mem


# ---- load/save --------------------------------------------------------------

def test_load_empty_when_no_file_and_no_seed(mem_env):
    mem = swarm_memory.load_swarm_memory()
    assert mem["session_count"] == 0
    assert mem["next_pursuits"] == []


def test_save_load_roundtrip(mem_env):
    mem = _base_memory(next_pursuits=[{"direction": "build the gate", "priority": "high"}])
    swarm_memory.save_swarm_memory(mem)
    loaded = swarm_memory.load_swarm_memory()
    assert loaded["next_pursuits"][0]["direction"] == "build the gate"
    assert loaded["last_updated"] is not None


def test_save_prunes_to_caps(mem_env):
    mem = _base_memory(
        next_pursuits=[{"direction": f"p{i}"} for i in range(30)])
    swarm_memory.save_swarm_memory(mem)
    loaded = swarm_memory.load_swarm_memory()
    assert len(loaded["next_pursuits"]) == swarm_memory.MEMORY_MAX_PURSUITS
    # [-N:] keeps the newest (end of list)
    assert loaded["next_pursuits"][-1]["direction"] == "p29"


# ---- pursuits: merge, not replace -------------------------------------------

def test_pursuits_carry_forward_when_not_restated(mem_env):
    swarm_memory.save_swarm_memory(_base_memory(
        next_pursuits=[{"direction": "Ship the quality gate", "priority": "high"}]))
    swarm_memory.update_swarm_memory("q", {
        "next_pursuits": [{"direction": "Wire the proposal bridge", "priority": "medium"}],
    })
    mem = swarm_memory.load_swarm_memory()
    directions = [p["direction"] for p in mem["next_pursuits"]]
    # The old pursuit survived (previously: wholesale replacement dropped it)
    assert "Ship the quality gate" in directions
    assert "Wire the proposal bridge" in directions
    carried = next(p for p in mem["next_pursuits"] if p["direction"] == "Ship the quality gate")
    assert carried["carried_sessions"] == 1
    # Carried pursuits sit BEFORE new ones so the cap drops stalest first
    assert directions.index("Ship the quality gate") < directions.index("Wire the proposal bridge")


def test_restated_pursuit_replaced_not_duplicated(mem_env):
    swarm_memory.save_swarm_memory(_base_memory(
        next_pursuits=[{"direction": "Ship the Quality Gate", "carried_sessions": 3}]))
    swarm_memory.update_swarm_memory("q", {
        "next_pursuits": [{"direction": "ship the quality gate", "priority": "high"}],
    })
    mem = swarm_memory.load_swarm_memory()
    assert len(mem["next_pursuits"]) == 1
    # Fresh copy wins; the stale carried counter is gone
    assert mem["next_pursuits"][0].get("carried_sessions", 0) == 0


def test_empty_delta_pursuits_keeps_existing(mem_env):
    swarm_memory.save_swarm_memory(_base_memory(
        next_pursuits=[{"direction": "still owed"}]))
    swarm_memory.update_swarm_memory("q", {"resolved_positions": []})
    mem = swarm_memory.load_swarm_memory()
    assert mem["next_pursuits"][0]["direction"] == "still owed"


# ---- question resolution -----------------------------------------------------

def test_explicit_resolved_question_closes(mem_env):
    swarm_memory.save_swarm_memory(_base_memory(unresolved_questions=[
        {"question": "Does verify_round_claims() actually exist and is it wrappable?", "attempts": 3},
        {"question": "What is the Kata severity calibration rule?", "attempts": 1},
    ]))
    swarm_memory.update_swarm_memory("q", {
        "resolved_questions": ["Does verify_round_claims() actually exist and is it wrappable?"],
    })
    mem = swarm_memory.load_swarm_memory()
    remaining = [q["question"] for q in mem["unresolved_questions"]]
    assert remaining == ["What is the Kata severity calibration rule?"]


def test_topic_containment_fallback_closes_question(mem_env):
    swarm_memory.save_swarm_memory(_base_memory(unresolved_questions=[
        {"question": "Should the tool allowlist be deny-by-default in Joy Mode?", "attempts": 2},
    ]))
    # Topic tokens ("tool allowlist deny-by-default") mostly appear in the question
    swarm_memory.update_swarm_memory("q", {
        "resolved_positions": [
            {"topic": "tool allowlist deny-by-default", "consensus": "yes, hard gate", "confidence": "high"},
        ],
    })
    mem = swarm_memory.load_swarm_memory()
    assert mem["unresolved_questions"] == []


def test_unrelated_topic_does_not_close_question(mem_env):
    swarm_memory.save_swarm_memory(_base_memory(unresolved_questions=[
        {"question": "Should the tool allowlist be deny-by-default in Joy Mode?", "attempts": 2},
    ]))
    swarm_memory.update_swarm_memory("q", {
        "resolved_positions": [
            {"topic": "prosody voice casting", "consensus": "keep five voices", "confidence": "medium"},
        ],
    })
    mem = swarm_memory.load_swarm_memory()
    assert len(mem["unresolved_questions"]) == 1


def test_repeat_question_increments_attempts(mem_env):
    swarm_memory.save_swarm_memory(_base_memory(unresolved_questions=[
        {"question": "What is the Kata severity rule?", "attempts": 1},
    ]))
    swarm_memory.update_swarm_memory("q", {
        "unresolved_questions": [{"question": "what is the kata severity rule?", "raised_by": "grok"}],
    })
    mem = swarm_memory.load_swarm_memory()
    assert len(mem["unresolved_questions"]) == 1
    assert mem["unresolved_questions"][0]["attempts"] == 2


# ---- supersession ------------------------------------------------------------

def test_reresolved_topic_marks_old_superseded_but_keeps_it(mem_env):
    swarm_memory.save_swarm_memory(_base_memory(resolved_positions=[
        {"topic": "gate rollout", "consensus": "blocking from day one", "confidence": "medium"},
    ]))
    swarm_memory.update_swarm_memory("q", {
        "resolved_positions": [
            {"topic": "Gate Rollout", "consensus": "score-only first", "confidence": "high"},
        ],
    })
    mem = swarm_memory.load_swarm_memory()
    # Supersede, don't forget: both entries stored
    assert len(mem["resolved_positions"]) == 2
    old, new = mem["resolved_positions"]
    assert old["status"] == "superseded"
    assert "superseded_at" in old
    assert new.get("status") != "superseded"


def test_format_injects_only_active_positions(mem_env):
    mem = _base_memory(resolved_positions=[
        {"topic": "old law", "consensus": "stale", "status": "superseded"},
        {"topic": "current law", "consensus": "live", "confidence": "high"},
    ])
    ctx = swarm_memory.format_memory_context(mem)
    assert "current law" in ctx
    assert "old law" not in ctx


def test_format_shows_carried_counter(mem_env):
    mem = _base_memory(next_pursuits=[
        {"direction": "the forgotten pursuit", "carried_sessions": 4},
    ])
    ctx = swarm_memory.format_memory_context(mem)
    assert "carried 4 sessions" in ctx


def test_format_empty_memory_is_empty_string(mem_env):
    assert swarm_memory.format_memory_context(swarm_memory.empty_memory()) == ""


# ---- misc --------------------------------------------------------------------

def test_update_with_none_delta_is_noop(mem_env):
    assert swarm_memory.update_swarm_memory("q", None) is None
    assert not swarm_memory.memory_file().exists()


def test_session_log_records_closures(mem_env):
    swarm_memory.save_swarm_memory(_base_memory(unresolved_questions=[
        {"question": "Will this be closed?", "attempts": 1},
    ]))
    swarm_memory.update_swarm_memory("the query", {
        "resolved_questions": ["Will this be closed?"],
    })
    mem = swarm_memory.load_swarm_memory()
    assert mem["session_log"][-1]["questions_closed"] == 1
