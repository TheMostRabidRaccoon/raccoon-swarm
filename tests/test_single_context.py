"""Tests for one-shot Single Swarm continuity semantics."""
from pathlib import Path

import swarm_single_context as single


def test_single_prompt_contains_compact_memory_and_relevance_recall():
    prompt = single.build_prompt(
        query="What did we decide about memory?",
        file_text="attached evidence",
        boot_context="manual carry-forward",
        memory_context="=== SWARM PERSISTENT MEMORY ===\nresolved position",
        recall_context="=== RELEVANT PRIOR CONTEXT — AUTOMATIC RECALL ===\nold evidence",
    )
    assert "=== BOOT CONTEXT ===" in prompt
    assert "SWARM PERSISTENT MEMORY" in prompt
    assert "AUTOMATIC RECALL" in prompt
    assert "=== ATTACHED FILES ===" in prompt
    assert prompt.rstrip().endswith(
        "=== TASK ===\nWhat did we decide about memory?\n=== END TASK ==="
    )


def test_boot_context_switch_does_not_control_memory_continuity():
    prompt = single.build_prompt(
        query="continue",
        file_text="",
        boot_context="",
        memory_context="durable compact memory",
        recall_context="relevant prior evidence",
    )
    assert "BOOT CONTEXT" not in prompt
    assert "durable compact memory" in prompt
    assert "relevant prior evidence" in prompt
    assert "=== TASK ===\ncontinue\n=== END TASK ===" in prompt


def test_single_prompt_can_be_current_task_only_when_memory_surfaces_are_empty():
    prompt = single.build_prompt(
        query="brand new problem",
        file_text="",
        boot_context="",
        memory_context="",
        recall_context="",
    )
    assert prompt == "=== TASK ===\nbrand new problem\n=== END TASK ==="


def test_active_entry_installs_single_swarm_continuity_adapter():
    server = (Path(__file__).resolve().parents[1] / "raccoon_swarm_server.py").read_text()
    assert "swarm_single_context.install(runtime, swarm_recall)" in server
