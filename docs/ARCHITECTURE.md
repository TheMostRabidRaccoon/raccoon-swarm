# Architecture

Raccoon Swarm now separates **cognitive semantics**, **runtime orchestration**, and **hard environmental boundaries**.

That separation is intentional. Natural-language context shapes what a participant notices and considers relevant; code determines what state is visible, which direct actuators are exposed on a given surface, and how consequential actions are routed.

## Layers

```text
Kyra / external request
        │
        ▼
swarm_ecology.py
  peer standing · attentional roles · exploration · thread sovereignty
  capability/action-surface semantics · Claude/GPT reliability-routed final review
        │
        ├── swarm_memory_policy.py
        │     selective persistence / autonomous-pursuit semantics
        │
        ▼
raccoon_swarm_server.py
  active entry point: installs current ecology + current model registry
        │
        ▼
swarm_runtime.py
  Flask · SSE · provider SDK loops · daemon · headless · UI · media pipelines
        │
        ├── swarm_tools.py          shared model tool registry
        ├── swarm_filestore.py      external memory + write/ghost verification
        ├── swarm_memory.py         compact cross-session state
        ├── swarm_semantic.py       embedding/hybrid retrieval
        ├── swarm_evidence.py       provenance-carrying evidence catalog
        ├── swarm_codeexec.py       bounded execution + receipts
        ├── swarm_imagegen.py       image-generation backends
        ├── swarm_websearch.py      public-web search
        ├── swarm_webverify.py      narrow URL verification
        ├── swarm_prosody.py        prosody/TTS service bridge
        ├── swarm_workspace.py      fenced repository workspace
        ├── swarm_dispatch.py       deterministic production queue
        ├── swarm_closer.py         mechanical post-session telemetry
        ├── swarm_orchestrator.py   tool-budget wind-down
        └── swarm_joy.py            bounded autonomous ritual
```

## Cognitive unit of analysis

The architecture does not assume that capability belongs only to one model. Depending on the question, the useful unit may be:

- a model alone;
- model + current context;
- model + tool;
- model + external memory;
- a sequence of models transforming one another's representations;
- Kyra + models + tools + persistent state.

This is why roles are not implemented as permissions. **Backbone**, **Integrator**, **Chaos Processor**, **Court Bard**, **Oracle**, and **Conductor** are cultural identities and attentional signatures.

> **Do not mistake the current division of labor for the boundary of anyone's capability.**

## Capability is not the action surface

Four properties that were previously easy to collapse are now kept separate:

1. **Capability** — what a participant can reason about, understand, design, critique, or learn to do.
2. **Observability** — what evidence/state is visible on the present surface.
3. **Actuation** — which direct operations the present interface exposes.
4. **Integration route** — how a result reaches a consequential external system.

A missing actuator is not a cognitive diagnosis. If a production merge is routed through a human-reviewed surface, that says how the action enters production; it does not imply that another participant cannot inspect, design, critique, test, or substantially complete the change.

The preferred language is therefore **"not exposed on this surface"**, **"not visible from this observation channel"**, or **"routes through this review gate"** rather than turning a local interface condition into a global statement of incapacity.

## Request → cognition → persistence

```text
HTTP / headless / daemon request
  │
  ├── authentication + deployment profile      [hard gate]
  │
  ▼
active peer-ecology system prompt
  │
  ▼
model round(s)
  │    ├── shared tool calls
  │    ├── parallel or daisy interaction
  │    └── optional human turn
  │
  ▼
Claude + GPT independent integration
  │
  ▼
final integration
  │
  ├── selective memory extraction
  ├── verified filestore writes when warranted
  ├── mechanical closer / telemetry
  └── output log / DOCX / downstream artifact
```

The Claude/GPT final-review pair is **competence routing, not seniority**. Both remain challengeable by every participant. Claude emits the final merge string because one API call must emit a string; that mechanical position does not make Claude the superior node.

## Persistence is not operationalization

The July 2026 architecture made persistence very good at answering **"did this idea survive the session?"** That is not the same question as **"did this idea change the running system?"**

For system-change work, keep these states distinct:

```text
observed → proposed → persisted → implemented → integrated/deployed → behaviorally verified
```

A framework file may be a valuable continuity object while still being only a proposal. A change request is not complete merely because its rationale exists on disk.

## Model registry

Provider model versions are isolated in `swarm_model_config.py` so model upgrades do not rewrite the seat ontology.

Current general-seat defaults are:

- Claude → `claude-fable-5`
- GPT → `gpt-5.6-sol`, explicit high reasoning
- Grok → `grok-4.5`, explicit high reasoning
- Gemini → `gemini-3.1-pro-preview`
- Perplexity → `sonar-pro`

Nested-agent modes are deliberately separate topology choices rather than silently substituted models. The registry also records `grok-4.20-multi-agent` as an optional xAI multi-agent route and GPT-5.6 `ultra` as a future Responses-API multi-agent route.

Every value is environment-overridable for rollback or A/B testing.

## Shared action space

Claude, GPT, Grok, and Gemini receive the same unified tool registry where their current provider interfaces support native tool calling. A habitual specialty does not imply ownership of a tool or task type.

Examples:

- Gemini may normally notice visual representation first, but Claude may invoke image generation when that is the best available path.
- Grok may normally stress-test assumptions, but it may synthesize, research, code, or build when useful.
- GPT may normally integrate systems, but exploration does not need to end in architecture.
- Claude may normally track coherence, but it is not the supervisor of the other nodes.

When one surface exposes a narrower set of direct actuators, work can route through another participant or interface without turning that routing difference into a capability hierarchy.

## Current repository surfaces

`swarm_workspace.py` exposes a low-blast-radius GitHub construction surface in `swarm-lab`: job branches, file writes, and draft PRs. The production source repository is intentionally outside that **write surface**.

That is an integration design, not a statement that the ecology is incapable of reasoning about its own source. A separate, read-only self-observation surface is the cleaner future route for first-class source inspection because it can expose the exact deployed source/SHA without expanding production mutation authority.

## Memory

Two persistence layers coexist:

1. `swarm_memory.py` — compact cross-session state used by headless/daemon continuation.
2. `swarm_filestore.py` — richer shared external memory and durable artifacts.

`swarm_memory_policy.py` applies a selective-memory test. The system favors costly mistakes, behavior-changing insights, high-value human continuity, compact recurring hazards, useful conceptual handles, deliberately parked threads, and reusable state.

It normally rejects routine agreement, ordinary tool success, competence receipts, transcript duplication, and lore that cannot guide future cognition.

This distinction matters because `next_pursuits` can drive autonomous daemon work: **interesting is not automatically obligatory**.

## Environment = physics

Hard boundaries remain code-enforced:

- secret / `.env` restrictions;
- repository and path allowlists;
- protected branches;
- auth and deployment posture;
- execution/network boundaries;
- merge and credential routes;
- runner-stamped provenance;
- write/read-back verification.

These are not evidence that one cognitive participant outranks another or possesses less general capability.

A useful shorthand is:

> **Language shapes the cognitive constitution; code defines the physics. The physics wins.**

## Transitional legacy prompt text

`swarm_runtime.py` currently contains historical prompt constants inherited from the pre-refactor monolith. The active entry point replaces `get_system_prompt`, synthesis behavior, exported prompt constants, and display semantics with `swarm_ecology.py` at runtime. Those historical strings are **inert compatibility residue**, not the active ontology.

They should eventually be removed or moved to an explicit history/archive module so source inspection presents one unambiguous semantic layer. Until then, `swarm_ecology.py` is the canonical active source for Council/role semantics.

## Historical governance modes

Round Table governance, declaration parsing, convergence analysis, the Existence Criterion, and prior procedural experiments remain part of the research record and may still be invoked as experimental topologies.

They no longer define the default ontology of the swarm.
