# Architecture

Raccoon Swarm now separates **cognitive semantics**, **runtime orchestration**, and **hard environmental boundaries**.

That separation is intentional. Natural-language roles can shape what a model notices or considers legitimate, but secrets, protected branches, deployment posture, and other invariants should be enforced mechanically.

## Layers

```text
Kyra / external request
        │
        ▼
swarm_ecology.py
  peer standing · attentional roles · exploration · thread sovereignty
  seat identities · Claude/GPT reliability-routed final review
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

The Claude/GPT final-review pair is **competence routing, not seniority**. Both remain challengeable by every participant. Claude emits the final merge string because one call must do so; that mechanical position does not make Claude the superior node.

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

Claude, GPT, Grok, and Gemini receive the same unified tool registry where the provider supports native tool calling. A habitual specialty does not imply ownership of a tool or task type.

Examples:

- Gemini may normally notice visual representation first, but Claude may invoke image generation when that is the best available path.
- Grok may normally stress-test assumptions, but it may synthesize, research, code, or build when useful.
- GPT may normally integrate systems, but exploration does not need to end in architecture.
- Claude may normally track coherence, but it is not the supervisor of the other nodes.

Technical inability to invoke a capability is an environmental fact, not a social rule.

## Memory

Two persistence layers coexist:

1. `swarm_memory.py` — compact cross-session state used by headless/daemon continuation.
2. `swarm_filestore.py` — richer shared external memory and durable artifacts.

`swarm_memory_policy.py` now applies a selective-memory test. The system favors costly mistakes, behavior-changing insights, high-value human continuity, compact recurring hazards, useful conceptual handles, deliberately parked threads, and reusable state.

It normally rejects routine agreement, ordinary tool success, competence receipts, transcript duplication, and lore that cannot guide future cognition.

This distinction matters because `next_pursuits` can drive autonomous daemon work: **interesting is not automatically obligatory**.

## Environment = physics

Hard boundaries remain code-enforced:

- secret / `.env` restrictions;
- repository and path allowlists;
- protected branches;
- auth and deployment posture;
- execution/network boundaries;
- merge and credential gates;
- runner-stamped provenance;
- write/read-back verification.

These are not evidence that one cognitive participant outranks another.

A useful shorthand is:

> **Language shapes the cognitive constitution; code defines the physics. The physics wins.**

## Historical governance modes

Round Table governance, declaration parsing, convergence analysis, the Existence Criterion, and prior procedural experiments remain part of the research record and may still be invoked as experimental topologies.

They no longer define the default ontology of the swarm.
