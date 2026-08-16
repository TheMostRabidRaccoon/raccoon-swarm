"""Tests for Claude Fable refusal semantics."""
from types import SimpleNamespace

import swarm_claude_adapter as adapter


def _fake_runtime(message, tools_enabled=False):
    class Messages:
        def create(self, **kwargs):
            return message

    client = SimpleNamespace(messages=Messages())
    logger = SimpleNamespace(warning=lambda *a, **k: None, error=lambda *a, **k: None)
    tools = SimpleNamespace(tools_for_anthropic=lambda: [], dispatch=lambda *a, **k: {})
    orchestrator = SimpleNamespace(annotate_tool_result=lambda content, *a: content)
    return SimpleNamespace(
        CLAUDE_MODEL="claude-fable-5",
        get_claude_client=lambda: client,
        get_system_prompt=lambda name: "system",
        _claude_initial_user_content=lambda query, images: query,
        _extract_claude_text=lambda blocks: "\n".join(
            b.text for b in blocks if getattr(b, "type", None) == "text" and b.text
        ),
        _mcp_tools_enabled=lambda: tools_enabled,
        _max_tool_iterations=lambda: 3,
        swarm_tools=tools,
        swarm_orchestrator=orchestrator,
        logger=logger,
    )


def test_refusal_is_machine_recognizable_with_category():
    msg = SimpleNamespace(
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="cyber"),
    )
    out = adapter.refusal_result(msg)
    assert out == "[Claude refusal: category=cyber]"
    assert adapter.is_unavailable_output(out) is True


def test_refusal_without_category_is_still_machine_recognizable():
    msg = SimpleNamespace(stop_reason="refusal", stop_details=None)
    out = adapter.refusal_result(msg)
    assert out == "[Claude refusal: stop_reason=refusal]"
    assert adapter.is_unavailable_output(out) is True


def test_empty_no_text_errors_and_exhaustion_are_unavailable():
    for value in (
        "",
        None,
        "[Claude returned no text]",
        "[Claude error: boom]",
        "[Claude tool-use loop exhausted at 15 iterations without producing any text]",
    ):
        assert adapter.is_unavailable_output(value) is True


def test_normal_claude_text_is_available():
    assert adapter.is_unavailable_output("A supported integration result.") is False


def test_tool_disabled_refusal_branches_on_stop_reason():
    msg = SimpleNamespace(
        stop_reason="refusal",
        stop_details=SimpleNamespace(category="classifier"),
        content=[],
    )
    out = adapter.call(_fake_runtime(msg, tools_enabled=False), "query", max_tokens=100)
    assert out == "[Claude refusal: category=classifier]"


def test_tool_loop_refusal_discards_partial_text_instead_of_promoting_it():
    msg = SimpleNamespace(
        stop_reason="refusal",
        stop_details=None,
        content=[SimpleNamespace(type="text", text="partial text that must not win")],
    )
    out = adapter.call(_fake_runtime(msg, tools_enabled=True), "query", max_tokens=100)
    assert out == "[Claude refusal: stop_reason=refusal]"
    assert "partial text" not in out


def test_normal_tool_disabled_response_survives_adapter():
    msg = SimpleNamespace(
        stop_reason="end_turn",
        stop_details=None,
        content=[SimpleNamespace(type="text", text="usable answer")],
    )
    out = adapter.call(_fake_runtime(msg, tools_enabled=False), "query", max_tokens=100)
    assert out == "usable answer"
