#!/usr/bin/env python3
"""RRI Raccoon Swarm — active peer-cognitive-ecology entry point.

The Flask/model/tool plumbing lives in :mod:`swarm_runtime`. Prompt ontology is
kept separate in :mod:`swarm_ecology`, memory-selection semantics live in
:mod:`swarm_memory_policy`, provider model/version choices live in
:mod:`swarm_model_config`, :mod:`swarm_recall` activates relevant prior context,
:mod:`swarm_drive` exposes read-only external Drive evidence, and
:mod:`swarm_source` exposes the deployed checkout as a read-only self-observation
surface.

This separation is deliberate: changing what "Backbone", "Council", or
"Conductor" means should not require editing transport machinery, upgrading a
provider model should not rewrite a seat's cultural identity, and observing source
or Drive should not imply a production mutation route.
"""
from __future__ import annotations

import os
import threading

import swarm_claude_adapter
import swarm_closer_policy as closer_policy
import swarm_drive
import swarm_ecology as ecology
import swarm_memory_policy as memory_policy
import swarm_recall
import swarm_single_context
import swarm_source

# IMPORTANT: swarm_runtime loads ~/.env and the project .env at import time. Import it
# BEFORE swarm_model_config, whose constants are evaluated from os.environ at import.
# This makes local RRI_* model/reasoning overrides real rather than decorative.
import swarm_runtime as runtime
import swarm_model_config as model_config


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


# Claude Fable 5 can return HTTP-200 classifier refusals with empty content. The
# adapter preserves refusal as a first-class unavailable result instead of turning it
# into a false-success "returned no text" string.
def call_claude(query, max_tokens=runtime.MAX_OUTPUT_TOKENS, images=None, session_id="unknown"):
    return swarm_claude_adapter.call(
        runtime,
        query,
        max_tokens=max_tokens,
        images=images,
        session_id=session_id,
    )


runtime.call_claude = call_claude
runtime.SWARM_SINGLE["claude"] = call_claude
runtime.SWARM_LOOP["Claude"] = call_claude


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
# Observation + recall + generic change handoff.
# ---------------------------------------------------------------------------
# The live provider converters read TOOL_DEFINITIONS at call time. Source, memory
# recall, and Drive are observation/retrieval surfaces; none expand production
# mutation authority.
runtime.swarm_tools.TOOL_DEFINITIONS.update(swarm_source.tool_definitions())
runtime.swarm_tools.TOOL_DEFINITIONS.update(swarm_recall.tool_definitions())
runtime.swarm_tools.TOOL_DEFINITIONS.update(swarm_drive.tool_definitions())


def _dispatch_change_propose(
    name: str,
    summary: str,
    proposed_change: str,
    change_kind: str = "architecture",
    observation: str = "",
    evidence: str = "",
    expected_effect: str = "",
    validation: str = "",
    risk_notes: str = "",
    source_sha: str = "",
    model: str = "unknown",
    session_id: str = "unknown",
) -> dict:
    observed_sha = source_sha or (swarm_source.status().get("source_sha") or "")
    result = runtime.swarm_proposals.queue_change(
        name=name,
        summary=summary,
        proposed_change=proposed_change,
        change_kind=change_kind,
        observation=observation,
        evidence=evidence,
        expected_effect=expected_effect,
        validation=validation,
        risk_notes=risk_notes,
        source_sha=observed_sha,
        source=f"tool:{session_id}/{model}",
    )
    if result.get("ok"):
        result["operationalization_state"] = "persisted-review-handoff"
        result["implemented"] = False
        result["integrated_or_deployed"] = False
        result["behaviorally_verified"] = False
    return result


runtime.swarm_tools.TOOL_DEFINITIONS["change_propose"] = {
    "description": (
        "Create a structured review handoff when you identify a change worth making to the "
        "swarm or a related system. This may be an architecture, prompt, memory, tool, code, "
        "documentation, eval, workflow, UI, or research change. Use source_* evidence when the "
        "proposal concerns current source. Filing the proposal preserves and routes the change "
        "hypothesis; it does NOT mean the change is implemented, integrated, deployed, or "
        "behaviorally verified. Those states remain explicit."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short human-readable change name."},
            "summary": {"type": "string", "description": "Why this change is worth review."},
            "proposed_change": {"type": "string", "description": "Concrete change being proposed."},
            "change_kind": {
                "type": "string",
                "description": "architecture, prompt, memory, tool, code, docs, eval, workflow, ui, research, or other.",
            },
            "observation": {"type": "string", "description": "Observed problem, gap, or opportunity."},
            "evidence": {"type": "string", "description": "Supporting evidence, preferably source paths/lines or tool receipts."},
            "expected_effect": {"type": "string", "description": "Expected behavioral/system effect if implemented."},
            "validation": {"type": "string", "description": "How to test or falsify whether the change helped."},
            "risk_notes": {"type": "string", "description": "Risks, collision modes, rollback/reversibility notes."},
            "source_sha": {"type": "string", "description": "Optional explicit source SHA; current observed SHA is stamped when omitted."},
        },
        "required": ["name", "summary", "proposed_change"],
    },
    "dispatch": _dispatch_change_propose,
}

# Runner-stamp model/session provenance for the new generic handoff. The legacy
# registry dispatcher only has special injection cases for older tools, so keep
# its behavior intact and intercept this one tool at the runner boundary.
_original_tool_dispatch = runtime.swarm_tools.dispatch


def _ecology_tool_dispatch(name: str, args: dict, calling_model: str = "unknown",
                           session_id: str = "unknown") -> dict:
    if name == "change_propose":
        params = (args or {}).copy()
        params.setdefault("model", calling_model)
        params.setdefault("session_id", session_id)
        try:
            return _dispatch_change_propose(**params)
        except TypeError as exc:
            return {"error": f"bad args for change_propose: {exc}"}
        except Exception as exc:
            runtime.logger.error(f"change_propose raised: {type(exc).__name__}: {exc}")
            return {"error": f"{type(exc).__name__}: {exc}"}
    return _original_tool_dispatch(
        name, args, calling_model=calling_model, session_id=session_id)


runtime.swarm_tools.dispatch = _ecology_tool_dispatch

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
# Automatic associative recall — once, before Round 1.
# ---------------------------------------------------------------------------
_original_run_loop_round = runtime.run_loop_round
_recall_sessions: set[str] = set()
_recall_lock = threading.Lock()


def _recall_prompt_once(prompt: str, session_id: str) -> str:
    if not swarm_recall.automatic_recall_enabled() or not session_id or session_id == "unknown":
        return prompt
    with _recall_lock:
        if session_id in _recall_sessions:
            return prompt
        if len(_recall_sessions) > 1000:
            _recall_sessions.clear()
        _recall_sessions.add(session_id)

    task = swarm_recall.extract_task(prompt)
    if not task:
        return prompt
    try:
        memory = runtime.load_swarm_memory()
        recalled = swarm_recall.automatic_recall(task, memory=memory)
        ctx = recalled.get("context") or ""
        runtime.logger.info(
            "automatic recall session=%s local=%s drive=%s context_chars=%s",
            session_id,
            len(recalled.get("local") or []),
            len(recalled.get("drive") or []),
            len(ctx),
        )
        return f"{ctx}\n\n{prompt}" if ctx else prompt
    except Exception as exc:
        runtime.logger.error(
            f"automatic recall failed for {session_id} (non-fatal): "
            f"{type(exc).__name__}: {exc}"
        )
        return prompt


def run_loop_round(prompt, models=None, images=None, session_id="unknown",
                   mode="parallel", order=None, on_speaker=None):
    recalled_prompt = _recall_prompt_once(prompt, session_id)
    return _original_run_loop_round(
        recalled_prompt,
        models=models,
        images=images,
        session_id=session_id,
        mode=mode,
        order=order,
        on_speaker=on_speaker,
    )


runtime.run_loop_round = run_loop_round

# Single Swarm bypasses run_loop_round entirely, so install an equivalent endpoint
# adapter that supplies compact continuity + automatic relevance recall before the
# one-shot parallel dispatch.
swarm_single_context.install(runtime, swarm_recall)


# ---------------------------------------------------------------------------
# Mechanical closer: telemetry always, interruption only when useful by default.
# ---------------------------------------------------------------------------
_original_closer_send = runtime.swarm_closer._send_via_smtp


def _ecology_closer_send(subject: str, body: str, session_id: str):
    mode = closer_policy.notify_mode()
    if closer_policy.should_notify(subject, body, mode=mode):
        return _original_closer_send(subject, body, session_id)
    return False, closer_policy.suppressed_reason(mode)


runtime.swarm_closer._send_via_smtp = _ecology_closer_send


# ---------------------------------------------------------------------------
# Dual final-review integration — Claude + GPT remain the reliability pair.
# ---------------------------------------------------------------------------
def _integration_failed(label: str, text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return True
    if label.lower() == "claude" and swarm_claude_adapter.is_unavailable_output(text):
        return True
    return low.startswith((
        f"[{label.lower()} error",
        f"[{label.lower()} synthesis error",
        f"[{label.lower()} returned no text",
    )) or "synthesis error" in low[:120]


def run_synthesis(query, all_rounds):
    """Integrate a session through the Claude/GPT reliability pair.

    Both models independently integrate the same transcript. A Claude classifier
    refusal is an unavailable review result, not a successful empty synthesis. If
    Claude is unavailable at either the independent-review or final-merge step, the
    valid GPT integration survives instead of being discarded.
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
        runtime.logger.warning("Claude independent integration unavailable; using GPT integration")
        return gpt_integration
    if gpt_bad and not claude_bad:
        return claude_integration
    if claude_bad and gpt_bad:
        return f"{claude_integration}\n\n{gpt_integration}"

    merged = runtime.call_claude(
        ecology.merge_prompt(claude_integration, gpt_integration),
        max_tokens=runtime.MAX_OUTPUT_TOKENS,
    )
    if _integration_failed("claude", merged):
        runtime.logger.warning(
            "Claude final integration unavailable; preserving valid GPT independent integration"
        )
        return gpt_integration
    return merged


runtime.run_synthesis = run_synthesis


# ---------------------------------------------------------------------------
# Current display semantics.
# ---------------------------------------------------------------------------
if "gpt" in runtime.VOICE_CAST:
    runtime.VOICE_CAST["gpt"]["label"] = "Integrator"

for _key, _label in ecology.DISPLAY_LABELS.items():
    if hasattr(runtime, "VOICE_CAST_LABELS"):
        runtime.VOICE_CAST_LABELS[_key] = _label
        runtime.VOICE_CAST_LABELS[_key.capitalize() if _key != "gpt" else "GPT"] = _label

runtime.HOME_HTML = runtime.HOME_HTML.replace(
    "Eric — Integrator — Full Council Member", "Eric — Integrator")
runtime.HOME_HTML = runtime.HOME_HTML.replace(
    "Claude synthesizing...", "Claude + GPT integrating...")

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


# Add live model/source/memory metadata to /config without changing the original
# runtime route contract.
_original_config = runtime.config


def config():
    response = _original_config()
    try:
        payload = response.get_json()
        payload["seat_models"] = model_config.SEAT_MODELS
        payload["source_observation"] = swarm_source.status()
        payload["drive_observation"] = swarm_drive.status()
        payload["automatic_recall"] = {
            "enabled": swarm_recall.automatic_recall_enabled(),
            "drive_enabled": swarm_recall.automatic_drive_recall_enabled(),
        }
        payload["closer_notify_mode"] = closer_policy.notify_mode()
        return runtime.jsonify(payload)
    except Exception:
        return response


runtime.app.view_functions["config"] = config


# Flask / gunicorn entry point.
app = runtime.app


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
    drive_state = swarm_drive.status()
    print(f"Drive observation: {'configured' if drive_state.get('configured') else 'not configured'}")
    print(
        f"Automatic recall: {'on' if swarm_recall.automatic_recall_enabled() else 'off'} "
        f"(Drive {'on' if swarm_recall.automatic_drive_recall_enabled() else 'off'})"
    )
    print(f"Closer notifications: {closer_policy.notify_mode()} (telemetry remains local)")
    print(f"Local: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
