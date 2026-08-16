#!/usr/bin/env python3
"""RRI Raccoon Swarm — active peer-cognitive-ecology entry point.

The Flask/model/tool plumbing lives in :mod:`swarm_runtime`. Prompt ontology is
kept separate in :mod:`swarm_ecology`, memory-selection semantics live in
:mod:`swarm_memory_policy`, provider model/version choices live in
:mod:`swarm_model_config`, and :mod:`swarm_source` exposes the deployed checkout
as a read-only self-observation surface.

This separation is deliberate: changing what "Backbone", "Council", or
"Conductor" means should not require editing transport machinery, upgrading a
provider model should not rewrite a seat's cultural identity, and observing source
should not imply a production mutation route.
"""
from __future__ import annotations

import os

import swarm_ecology as ecology
import swarm_memory_policy as memory_policy
import swarm_model_config as model_config
import swarm_source
import swarm_runtime as runtime


# ---------------------------------------------------------------------------
# Install current provider models. Environment variables in swarm_model_config
# remain the rollback / A-B-test escape hatch.
# ---------------------------------------------------------------------------
runtime.CLAUDE_MODEL = model_config.CLAUDE_MODEL
runtime.GPT_MODEL = model_config.GPT_MODEL
runtime.GROK_MODEL = model_config.GROK_MODEL
runtime.GEMINI_MODEL = model_config.GEMINI_MODEL
runtime.PERPLEXITY_MODEL = model_config.PERPLEXITY_MODEL
runtime.GROK_REASONING_EFFORT = model_config.GROK_REASONING_EFFORT


# GPT-5.6 supports explicit reasoning effort. The legacy runtime helper already
# carries provider-specific parameters through `extra_body`; use that path so
# the Integrator does not silently fall back to the API's medium default.
def call_gpt(query, max_tokens=runtime.MAX_OUTPUT_TOKENS, images=None, session_id="unknown"):
    try:
        return runtime._openai_chat_with_tools(
            client=runtime.get_gpt_client(),
            model_name=runtime.GPT_MODEL,
            max_tokens=max_tokens,
            tokens_param="max_completion_tokens",
            sys_prompt=runtime.get_system_prompt("gpt"),
            query=query,
            images=images,
            calling_model="gpt",
            label="GPT",
            session_id=session_id,
            extra_body={"reasoning_effort": model_config.GPT_REASONING_EFFORT},
        )
    except Exception as exc:
        runtime.logger.error(f"GPT Error: {exc}")
        return f"[GPT error: {str(exc)}]"


runtime.call_gpt = call_gpt
runtime.SWARM_SINGLE["gpt"] = call_gpt
runtime.SWARM_LOOP["GPT"] = call_gpt


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
# Source self-observation + routing-first tool semantics.
# ---------------------------------------------------------------------------
# The live provider converters read TOOL_DEFINITIONS at call time, so adding the
# source tools here immediately exposes them to every native-tool seat without
# expanding the fenced GitHub workspace token.
runtime.swarm_tools.TOOL_DEFINITIONS.update(swarm_source.tool_definitions())

# Several legacy tool descriptions encoded local interface boundaries as if they
# were participant incapabilities or social jurisdictions. Keep the underlying
# hard boundaries; describe them at the correct level.
if "code_exec" in runtime.swarm_tools.TOOL_DEFINITIONS:
    runtime.swarm_tools.TOOL_DEFINITIONS["code_exec"]["description"] = (
        "Execute Python code in an empty ephemeral execution sandbox and capture results. "
        "The repo source, persistent filestore, and prior artifacts are not mounted on this "
        "execution surface; obtain source through source_* tools and memory/artifacts through "
        "filestore_* tools, then pass the relevant data into the code. Relative files created "
        "during the run can be persisted as code-run artifacts. This boundary describes the "
        "sandbox surface, not the participant's ability to reason about source or stored data."
    )

if "workspace_status" in runtime.swarm_tools.TOOL_DEFINITIONS:
    runtime.swarm_tools.TOOL_DEFINITIONS["workspace_status"]["description"] = (
        "Report the fenced GitHub construction surface: configured sandbox repo(s), reachability, "
        "and base branch, without exposing credentials. This surface provides job branches and "
        "draft-PR handoff in allowlisted sandbox repos. Production-source observation is available "
        "separately through source_*; consequential integration routes through review rather than "
        "through this sandbox write surface."
    )

if "workspace_open_pr" in runtime.swarm_tools.TOOL_DEFINITIONS:
    runtime.swarm_tools.TOOL_DEFINITIONS["workspace_open_pr"]["description"] = (
        "Open a DRAFT pull request from a job branch into the base branch of an allowlisted "
        "sandbox repo. This is the construction-to-review handoff: the returned PR is a reviewable "
        "artifact; integration into a consequential environment occurs on a separate reviewed "
        "route. The PR body is stamped with model + session provenance."
    )

if "dispatch_queue_write" in runtime.swarm_tools.TOOL_DEFINITIONS:
    runtime.swarm_tools.TOOL_DEFINITIONS["dispatch_queue_write"]["description"] = (
        "Queue a deterministic scripted-episode production job (TTS + frames + ffmpeg -> MP4). "
        "Use when the current work has actually reached the production-ready scripted-episode "
        "state and the required script structure is present. Eligibility comes from the state of "
        "the artifact and its prerequisites, not from a seat identity or permanent owner role. "
        "The runner performs the production pipeline and reports completion/failure through the "
        "configured callback route."
    )


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


# Add live model/source metadata to /config without changing the original runtime
# route contract. The UI can display it later; tests/canaries can inspect it now.
_original_config = runtime.config


def config():
    response = _original_config()
    try:
        payload = response.get_json()
        payload["seat_models"] = model_config.SEAT_MODELS
        payload["source_observation"] = swarm_source.status()
        return runtime.jsonify(payload)
    except Exception:
        return response


runtime.app.view_functions["config"] = config


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
    print("Models:")
    for seat, cfg in model_config.SEAT_MODELS.items():
        effort = f" / {cfg['effort']}" if cfg.get("effort") else ""
        print(f"  {seat}: {cfg['model']}{effort}")
    print(f"Source observation: {swarm_source.status().get('source_sha') or 'SHA unavailable'}")
    print(f"Local: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
