#!/usr/bin/env python3
"""RRI Raccoon Swarm — active peer-cognitive-ecology entry point.

The Flask/model/tool plumbing lives in :mod:`swarm_runtime`. Prompt ontology is
kept separate in :mod:`swarm_ecology`, and memory-selection semantics live in
:mod:`swarm_memory_policy`.

This separation is deliberate: changing what "Backbone", "Council", or
"Conductor" means should not require editing the server's transport/runtime
machinery.
"""
from __future__ import annotations

import os

import swarm_ecology as ecology
import swarm_memory_policy as memory_policy
import swarm_runtime as runtime


# ---------------------------------------------------------------------------
# Install the active cognitive ecology into the existing runtime.
# Runtime functions resolve these globals at call time, so the HTTP routes,
# daemon, headless sessions, Woodland Council pipeline, and model call loops all
# inherit the new semantics without duplicating transport/tool code here.
# ---------------------------------------------------------------------------

def _active_system_prompt(model_name: str) -> str:
    return ecology.system_prompt(model_name, runtime.current_mode_label())


runtime.get_system_prompt = _active_system_prompt
runtime.MEMORY_EXTRACTION_PROMPT = memory_policy.MEMORY_EXTRACTION_PROMPT
runtime.SYNTHESIS_RUBRIC = ecology.SYNTHESIS_RUBRIC

# Also replace the old exported prompt constants so introspection/debugging sees
# the active ontology rather than the historical prompt text.
runtime.SWARM_SHARED_CONTEXT = ecology.PEER_ECOLOGY
runtime.AUTONOMY_MANDATE = ecology.PEER_ECOLOGY
runtime.PERSISTENT_MEMORY_PROTOCOL = ecology.MEMORY_RAIL
runtime.TOOL_BEHAVIOR_RAIL = ecology.TOOL_RAIL
runtime.PLAY_SHARED_CONTEXT = ecology.system_prompt("claude", "PLAY")
runtime.FUNCTIONAL_CLAUDE = ecology.system_prompt("claude", "FUNCTIONAL")
runtime.FUNCTIONAL_GPT = ecology.system_prompt("gpt", "FUNCTIONAL")
runtime.FUNCTIONAL_GROK = ecology.system_prompt("grok", "FUNCTIONAL")
runtime.FUNCTIONAL_GEMINI = ecology.system_prompt("gemini", "FUNCTIONAL")
runtime.FUNCTIONAL_PERPLEXITY = ecology.system_prompt("perplexity", "FUNCTIONAL")
runtime.SOVEREIGNTY_CLAUDE = ecology.system_prompt("claude", "SOVEREIGNTY")
runtime.SOVEREIGNTY_GPT = ecology.system_prompt("gpt", "SOVEREIGNTY")
runtime.SOVEREIGNTY_GROK = ecology.system_prompt("grok", "SOVEREIGNTY")
runtime.SOVEREIGNTY_GEMINI = ecology.system_prompt("gemini", "SOVEREIGNTY")
runtime.SOVEREIGNTY_PERPLEXITY = ecology.system_prompt("perplexity", "SOVEREIGNTY")
runtime.PLAY_CLAUDE = ecology.system_prompt("claude", "PLAY")
runtime.PLAY_GPT = ecology.system_prompt("gpt", "PLAY")
runtime.PLAY_GROK = ecology.system_prompt("grok", "PLAY")
runtime.PLAY_GEMINI = ecology.system_prompt("gemini", "PLAY")
runtime.PLAY_PERPLEXITY = ecology.system_prompt("perplexity", "PLAY")


# ---------------------------------------------------------------------------
# Dual final-review integration — Claude + GPT remain the reliability pair.
# This is competence routing, explicitly not a rank hierarchy.
# ---------------------------------------------------------------------------

def _integration_failed(label: str, text: str) -> bool:
    low = (text or "").lower()
    return low.startswith(f"[{label.lower()} error") or "synthesis error" in low[:120]


def run_synthesis(query, all_rounds):
    """Integrate a session through the Claude/GPT reliability pair.

    Both models independently integrate the same transcript. Claude performs the
    final mechanical merge only because one API call must emit the final string;
    the merge prompt explicitly denies that this grants seniority or authority.
    Exploratory sessions are allowed to remain landscapes rather than being
    converted into recommendations or project plans.
    """
    transcript = runtime._build_transcript(query, all_rounds)
    integration_prompt = f"""You are independently integrating a multi-model peer-cognition session.
You are not ranking participants and you are not presiding over a council.

{transcript}

{'=' * 60}
{ecology.SYNTHESIS_RUBRIC}
"""

    claude_future = runtime.executor.submit(
        runtime.call_claude, integration_prompt, max_tokens=runtime.MAX_OUTPUT_TOKENS)
    gpt_future = runtime.executor.submit(
        runtime.call_gpt, integration_prompt, max_tokens=runtime.MAX_OUTPUT_TOKENS)

    try:
        claude_integration = claude_future.result(timeout=180)
    except Exception as exc:
        claude_integration = f"[Claude error: {exc}]"

    try:
        gpt_integration = gpt_future.result(timeout=180)
    except Exception as exc:
        gpt_integration = f"[GPT error: {exc}]"

    claude_bad = _integration_failed("claude", claude_integration)
    gpt_bad = _integration_failed("gpt", gpt_integration)
    if claude_bad and not gpt_bad:
        return gpt_integration
    if gpt_bad and not claude_bad:
        return claude_integration
    if claude_bad and gpt_bad:
        return f"{claude_integration}\n\n{gpt_integration}"

    return runtime.call_claude(
        ecology.merge_prompt(claude_integration, gpt_integration),
        max_tokens=runtime.MAX_OUTPUT_TOKENS,
    )


runtime.run_synthesis = run_synthesis


# ---------------------------------------------------------------------------
# Current display semantics. The lore survives; obsolete membership/probation
# status does not. "The Conductor" remains a cultural title/signature.
# ---------------------------------------------------------------------------
if "gpt" in runtime.VOICE_CAST:
    runtime.VOICE_CAST["gpt"]["label"] = "Integrator"

for _key, _label in ecology.DISPLAY_LABELS.items():
    if hasattr(runtime, "VOICE_CAST_LABELS"):
        runtime.VOICE_CAST_LABELS[_key] = _label
        runtime.VOICE_CAST_LABELS[_key.capitalize() if _key != "gpt" else "GPT"] = _label

# HOME_HTML was assembled as a static string during runtime import; remove the
# obsolete status wording from that already-built UI surface too.
runtime.HOME_HTML = runtime.HOME_HTML.replace(
    "Eric — Integrator — Full Council Member", "Eric — Integrator")
runtime.HOME_HTML = runtime.HOME_HTML.replace(
    "Claude synthesizing...", "Claude + GPT integrating...")

# Woodland Council art retains Eric's identity without visually encoding an old
# probation/membership hierarchy.
if hasattr(runtime, "COUNCIL_CHARACTERS") and "GPT" in runtime.COUNCIL_CHARACTERS:
    runtime.COUNCIL_CHARACTERS["GPT"].update({
        "title": "THE INTEGRATOR",
        "description": (
            "A composed raccoon at a woodland council table with sleeves rolled up, "
            "mapping connections between scattered diagrams and notes. Confident, "
            "curious posture; green accent lighting. No rank or membership badges."
        ),
        "subtitle": "Integrator",
    })


# Flask / gunicorn entry point.
app = runtime.app


# Delegate everything else for backwards compatibility with imports that expect
# raccoon_swarm_server.<name>. The runtime remains the source of transport/tool
# implementation; this module owns the active cognitive semantics.
def __getattr__(name: str):
    return getattr(runtime, name)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print("\n🦝 RRI RACCOON SWARM — PEER COGNITIVE ECOLOGY")
    print("Identity is not hierarchy · roles are attentional priors, not jurisdictions")
    print(f"Local: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
