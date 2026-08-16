# Models

Five provider seats participate in the RRI peer cognitive ecology. Seat names and lore
are cultural identities / attentional priors, not exclusive job descriptions.

## Source of truth

- `swarm_model_config.py` — provider model IDs and reasoning-effort defaults.
- `raccoon_swarm_server.py` — active ecology entry point; installs the configured
  models into the transport runtime after environment loading.
- `swarm_runtime.py` — provider SDK clients and transport/tool loops.
- `swarm_ecology.py` — active seat semantics.
- `.env.example` — operator-facing override names.

`swarm_runtime` loads `~/.env` and the project `.env` before
`swarm_model_config` is imported by the active entry point, so `RRI_*` overrides are
resolved before the registry constants are evaluated.

## Current general-seat defaults

| Seat | Transport | Model env override | Default model | Attentional signature |
|---|---|---|---|---|
| Claude / George | Anthropic SDK | `RRI_CLAUDE_MODEL` | `claude-fable-5` | continuity, contradictions, evidence, coherence |
| GPT / Eric | OpenAI SDK | `RRI_GPT_MODEL` | `gpt-5.6-sol` | system structure, cross-domain integration, abstraction |
| Grok / Callum | OpenAI-compatible xAI API | `RRI_GROK_MODEL` | `grok-4.5` | fragile assumptions, adversarial pressure, weird useful branches |
| Gemini / Adam | Google GenAI SDK | `RRI_GEMINI_MODEL` | `gemini-3.1-pro-preview` | representation, multimodality, reframing |
| Perplexity / Daniel | OpenAI-compatible Perplexity API | `RRI_PERPLEXITY_MODEL` | `sonar-pro` | external evidence and provenance |

The current division of labor is not a capability boundary. Shared tools are routed by
relevance and available provider interfaces, not by jurisdiction.

## Reasoning effort

### GPT

`RRI_GPT_REASONING` defaults to `high` and is sent explicitly by the active GPT
adapter. The provider model ID and reasoning setting remain independently
environment-overridable.

### Grok

`RRI_GROK_REASONING` defaults to `high` for the ordinary `grok-4.5` seat.

The optional nested-agent xAI route is a different topology:

- `RRI_GROK_MULTI_AGENT_MODEL` defaults to `grok-4.20-multi-agent`;
- `RRI_GROK_MULTI_AGENT_EFFORT` defaults to `high`.

Do not silently substitute the nested-agent route for the ordinary Grok seat merely as
an effort upgrade; it changes the cognitive graph.

## Claude Fable refusal handling

Claude Fable can return a normal API response with `stop_reason="refusal"` and no text.
`swarm_claude_adapter.py` treats that as an explicit unavailable result rather than a
successful empty answer.

For the dual final-review path:

1. Claude and GPT integrate independently.
2. If Claude refuses or otherwise produces an unavailable result, the valid GPT
   integration survives.
3. If both independent integrations are valid, Claude performs the mechanical final
   merge.
4. If that final Claude merge refuses, the valid GPT independent integration is
   returned rather than discarded.

This is fallback at the swarm-review layer; it does not imply cognitive seniority.

## Output ceiling

`RRI_MAX_OUTPUT_TOKENS` controls the per-call output ceiling used by the runtime. Keep
provider-specific request limits in mind when changing it; verify each seat on the
actual deployed surface after a model/parameter change.

## Environment override / rollback workflow

To test or roll back one seat:

1. Set the relevant `RRI_*_MODEL` or reasoning environment variable.
2. Restart the running process so import-time registry values are re-evaluated.
3. Check `/config` to confirm the resolved registry.
4. Run a small live canary / swarm turn.
5. Check `/version` so a merged/configured change is not confused with the running
   process actually using it.

A provider ID can be syntactically valid in code while still failing on an account or
provider surface, so live verification remains the floor.

## Voice casting

Voice identity is separate from model selection:

| Seat | Voice name | Cultural label |
|---|---|---|
| Claude | George | The Snooty Librarian / Backbone |
| GPT | Eric | Integrator |
| Grok | Callum | Flame-Bearer / Chaos Processor |
| Gemini | Adam | Court Bard |
| Perplexity | Daniel | Oracle |

Changing a provider model should not silently rewrite the seat's cultural identity or
cognitive ontology.

## Session selection

Each seat can be enabled or disabled per session. In daisy mode, ordering is a
session-local topology choice rather than permanent rank. In parallel mode, selected
seats receive the same initial problem state. Claude/GPT final review is reliability
routing for consequential output, not a general hierarchy over the session.
