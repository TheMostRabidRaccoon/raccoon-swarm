"""Round Orchestrator — keeps the swarm's tool loops from running off the cliff.

Two responsibilities:

1. **Wind-down warnings** (in-loop, proactive). When a model is in the last few
   iterations of its tool budget, the orchestrator injects a budget note into
   the tool-result content the model sees on its next turn. Models read it as
   "wrap up — produce final text in the next 1-2 turns, don't start a new
   investigation." Prevents the session-104 failure mode: model spends all 15
   iterations on tool calls and gets cut off mid-thought.

2. **Post-hoc salvage** (out-of-loop, reactive). When a model DID hit the cap
   without producing closing prose, the orchestrator can re-invoke a fast
   model to summarize the partial reasoning into a 200-word closer. The
   salvage is annotated so readers know it's a post-hoc completion, not the
   model's original voice. Use from `scripts/salvage_session.py`.

Architecture note: the orchestrator is read-write but does NOT deliberate.
It executes things the system already committed to (injecting a budget
warning, salvaging a truncated response). The Observer reads what happened
weekly. The Orchestrator finishes what was started, per round. Different
roles in the same family.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger("SwarmVault")


# How many iterations before the cap should the wind-down warning kick in?
# Default 3 — i.e. with a 15-iteration cap, warnings start appearing in the
# tool results of iteration 12 onward. Configurable via
# RRI_ORCHESTRATOR_WINDDOWN_AT env var.
def _winddown_threshold() -> int:
    try:
        return max(1, int(os.getenv("RRI_ORCHESTRATOR_WINDDOWN_AT", "3")))
    except (TypeError, ValueError):
        return 3


def _enabled() -> bool:
    """Master switch. Default ON; set RRI_ORCHESTRATOR_ENABLED=false to disable."""
    return os.getenv("RRI_ORCHESTRATOR_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def budget_warning(iteration: int, max_iters: int) -> Optional[str]:
    """Return a budget-warning string to prepend to tool-result content if we're
    in the wind-down zone; otherwise None.

    `iteration` is zero-indexed (the iteration that just executed, about to be
    sent to the model on its next turn). `max_iters` is the cap.
    """
    if not _enabled():
        return None
    threshold = _winddown_threshold()
    remaining = max_iters - iteration - 1  # iterations after this one
    if remaining > threshold:
        return None
    if remaining <= 0:
        # Last iteration's tool results — model must produce text this turn or never.
        return (
            "[ORCHESTRATOR — last call]: Tool budget exhausted after this turn. "
            "Produce your final text response NOW. Do not request any more tools. "
            "If your reasoning isn't done, summarize what you have."
        )
    return (
        f"[ORCHESTRATOR — wind-down]: {remaining} tool iteration(s) remaining "
        f"({iteration + 1}/{max_iters} used). Produce your final text response in "
        f"the next {min(remaining, 2)} turn(s). Do not start new investigation "
        f"threads — wrap up what you have."
    )


def annotate_tool_result(result_content: str, iteration: int, max_iters: int) -> str:
    """Convenience: prepend the budget warning to a tool-result content string
    if one applies. Otherwise return the content unchanged. Models receive the
    annotated content the same way they receive normal tool output.
    """
    warning = budget_warning(iteration, max_iters)
    if not warning:
        return result_content
    return f"{warning}\n\n{result_content}"


def annotate_tool_result_dict(result, iteration: int, max_iters: int):
    """Same as annotate_tool_result but for tool results passed as dicts (Gemini
    uses Part.from_function_response with a dict response field). Returns the
    result with an "_orchestrator_note" key added when we're in wind-down,
    otherwise unchanged.
    """
    warning = budget_warning(iteration, max_iters)
    if not warning:
        return result
    if isinstance(result, dict):
        return {"_orchestrator_note": warning, **result}
    return {"_orchestrator_note": warning, "result": result}


# ── Post-hoc truncation salvage ──────────────────────────────────────

_TRUNCATION_RE = re.compile(
    r"\[note: (?P<model>\w+) tool-use loop hit the (?P<cap>\d+)-iteration cap.*?\]",
    re.DOTALL,
)
_EXHAUSTED_RE = re.compile(
    r"\[(?P<model>\w+) tool-use loop exhausted at \d+ iterations without producing any text\]",
    re.DOTALL,
)


def is_truncated(text: str) -> bool:
    """Detect if a model output ended because it hit the tool-iteration cap."""
    if not text:
        return False
    return bool(_TRUNCATION_RE.search(text) or _EXHAUSTED_RE.search(text))


def detect_truncations(round_results: dict) -> list[tuple[str, str]]:
    """Return [(model_name, partial_text), ...] for every truncated response in
    a round. Skips error markers and non-string outputs."""
    out: list[tuple[str, str]] = []
    for model, output in round_results.items():
        if model == "_meta" or not isinstance(output, str):
            continue
        if is_truncated(output):
            out.append((model, output))
    return out


SALVAGE_SYSTEM = """You are a salvage editor for a multi-model AI swarm. A model
ran out of tool-call budget mid-response and was cut off before producing its
closing thoughts. Your job: read the partial reasoning the model produced
(which may include text it wrote between tool calls), and write a SHORT
closing paragraph (max 200 words) that synthesizes the model's apparent
conclusion in the model's voice.

Rules:
- Speak AS the model, not ABOUT it. Don't say "the model concluded X." Say
  what it would have concluded.
- Do not invent facts the partial reasoning doesn't support.
- Do not add new arguments or new sources.
- If the partial reasoning didn't reach a conclusion, write a brief honest
  note saying what's still open, in the model's voice.
- Start your output with: "[SALVAGE NOTE: post-hoc completion by Round
  Orchestrator — model exhausted tool budget. The following is a synthesis
  of partial reasoning, not the model's original closing.]"
- Then the closing paragraph. Nothing else."""


def salvage_truncated_response(
    model_name: str,
    partial_text: str,
    original_query: str,
    anthropic_client=None,
    salvage_model: str = "claude-haiku-4-5-20251001",
) -> Optional[str]:
    """Call Claude Haiku to produce a closing paragraph for a truncated response.
    Returns the salvage text on success, or None on failure (network, no key, etc.)

    Caller is responsible for appending the salvage text to the truncated output
    or otherwise persisting it. This function does no I/O on the filestore.
    """
    if anthropic_client is None:
        try:
            import anthropic
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                logger.warning("salvage skipped: ANTHROPIC_API_KEY not set")
                return None
            anthropic_client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            logger.warning("salvage skipped: anthropic SDK not installed")
            return None

    prompt = (
        f"Original conductor query:\n{original_query[:2000]}\n\n"
        f"Truncated response from {model_name}:\n{partial_text[:8000]}"
    )

    try:
        msg = anthropic_client.messages.create(
            model=salvage_model,
            max_tokens=400,
            system=SALVAGE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return text.strip() if text else None
    except Exception as e:
        logger.error(f"salvage call failed for {model_name}: {type(e).__name__}: {e}")
        return None


def status() -> dict:
    return {
        "enabled": _enabled(),
        "winddown_threshold_iterations": _winddown_threshold(),
        "salvage_model": "claude-haiku-4-5-20251001",
    }
