"""Claude call adapter with explicit stop-reason handling.

Claude Fable 5 may return a successful HTTP response whose ``stop_reason`` is
``refusal`` and whose content is empty. That is neither a transport error nor a valid
integration result. This adapter preserves refusal as its own machine-recognizable
state so the peer-ecology synthesis layer can fall back to the independent GPT review
instead of mistaking ``[Claude returned no text]`` for success.

The adapter intentionally reuses the runtime's clients, prompt selection, tool registry,
and orchestration helpers. It changes response semantics, not Claude's action surface.
"""
from __future__ import annotations

import json


REFUSAL_PREFIX = "[Claude refusal:"


def refusal_result(message) -> str:
    details = getattr(message, "stop_details", None)
    category = getattr(details, "category", None) if details is not None else None
    if category:
        return f"{REFUSAL_PREFIX} category={category}]"
    return f"{REFUSAL_PREFIX} stop_reason=refusal]"


def is_unavailable_output(text: str | None) -> bool:
    """Whether a Claude result should not be treated as a successful answer."""
    low = (text or "").strip().lower()
    if not low:
        return True
    return low.startswith((
        "[claude error:",
        "[claude refusal:",
        "[claude returned no text]",
        "[claude tool-use loop exhausted",
    ))


def call(runtime, query, max_tokens, images=None, session_id="unknown") -> str:
    """Call Claude through the runtime's existing client/tool surfaces.

    Refusal is checked before any accumulated text is accepted. Anthropic can refuse
    after partial output; partial material from a refused turn is therefore discarded
    rather than promoted into a completed response.
    """
    try:
        client = runtime.get_claude_client()
        system = runtime.get_system_prompt("claude")
        messages = [{
            "role": "user",
            "content": runtime._claude_initial_user_content(query, images),
        }]

        if not runtime._mcp_tools_enabled():
            msg = client.messages.create(
                model=runtime.CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            if getattr(msg, "stop_reason", None) == "refusal":
                runtime.logger.warning("Claude refusal received on tool-disabled path")
                return refusal_result(msg)
            return runtime._extract_claude_text(msg.content) or "[Claude returned no text]"

        tools = runtime.swarm_tools.tools_for_anthropic()
        max_iters = runtime._max_tool_iterations()
        accumulated_text: list[str] = []

        for iteration in range(max_iters):
            msg = client.messages.create(
                model=runtime.CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
            )
            stop_reason = getattr(msg, "stop_reason", None)

            # Refusal is an explicit terminal state. Do this before accepting this
            # turn's text because a refusal can occur after partial output.
            if stop_reason == "refusal":
                runtime.logger.warning("Claude refusal received during tool loop")
                return refusal_result(msg)

            turn_text = runtime._extract_claude_text(msg.content)
            if turn_text:
                accumulated_text.append(turn_text)

            if stop_reason != "tool_use":
                final = "\n\n".join(accumulated_text) if accumulated_text else turn_text
                return final or "[Claude returned no text]"

            messages.append({
                "role": "assistant",
                "content": [b.model_dump() for b in msg.content],
            })

            tool_results = []
            for block in msg.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                result = runtime.swarm_tools.dispatch(
                    block.name,
                    block.input or {},
                    calling_model="claude",
                    session_id=session_id,
                )
                content = json.dumps(result, default=str)
                content = runtime.swarm_orchestrator.annotate_tool_result(
                    content, iteration, max_iters
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                })
            messages.append({"role": "user", "content": tool_results})

        runtime.logger.warning(
            f"Claude tool-use loop hit MAX_TOOL_ITERATIONS={max_iters}"
        )
        if accumulated_text:
            return (
                "\n\n".join(accumulated_text)
                + f"\n\n[note: Claude tool-use loop hit the {max_iters}-iteration cap "
                "before producing a final answer; the above is partial reasoning.]"
            )
        return (
            f"[Claude tool-use loop exhausted at {max_iters} iterations "
            "without producing any text]"
        )

    except Exception as exc:
        runtime.logger.error(f"Claude Error: {exc}")
        return f"[Claude error: {str(exc)}]"
