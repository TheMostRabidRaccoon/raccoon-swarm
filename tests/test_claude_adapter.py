"""Tests for Claude Fable refusal semantics."""
from types import SimpleNamespace

import swarm_claude_adapter as adapter


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
