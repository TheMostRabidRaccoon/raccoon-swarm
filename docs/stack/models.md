# Models

Five AI providers in the round-table plus the human "Conductor" slot. Voice
casting via ElevenLabs.

## Source of truth

- `raccoon_swarm_server.py` (SDK clients, call_* functions, voice map)
- `.env.example` (API key names)
- `README.md` (Swarm Roster table)

## Providers

| Model      | SDK / Transport                          | Env var             | Role                             | Voice (ElevenLabs) |
|------------|------------------------------------------|---------------------|----------------------------------|--------------------|
| Claude     | `anthropic` (official)                   | `ANTHROPIC_API_KEY` | Backbone — The Snooty Librarian  | George             |
| GPT        | `openai` (official)                      | `OPENAI_API_KEY`    | Integrator — Full Council Member | Eric               |
| Gemini     | `google-genai` (`from google import genai`) | `GOOGLE_API_KEY` | Visual + Research — Court Bard   | Adam               |
| Grok       | `openai` client with `base_url=https://api.x.ai/v1` | `XAI_API_KEY` (fallback `GROK_API_KEY`) | Chaos Processor — Flame-Bearer | Callum |
| Perplexity | `openai` client with `base_url=https://api.perplexity.ai` | `PERPLEXITY_API_KEY` | Research — The Oracle | Daniel |

Client init sites (as of current server):

- Grok client: `raccoon_swarm_server.py:91` (`get_grok_client`)
- Perplexity client: `raccoon_swarm_server.py:106` (`get_perplexity_client`)
- Claude / OpenAI / Gemini: direct SDK, imported at top of file

## Call functions

All live in `raccoon_swarm_server.py`. Signature:
`call_<model>(query, max_tokens=2000, images=None)`.

Dispatch dict (both lowercase and capitalized keys, around `:822`):
`call_claude`, `call_gpt`, `call_gemini`, `call_grok`, `call_perplexity`.

## Model IDs — one place to bump

All five seats resolve from env-overridable constants near the top of
`raccoon_swarm_server.py` (search `MODEL IDS`). Defaults as of the latest bump:

| Seat       | Constant           | Env override            | Default                    |
|------------|--------------------|-------------------------|----------------------------|
| Claude     | `CLAUDE_MODEL`     | `RRI_CLAUDE_MODEL`      | `claude-opus-4-8`          |
| GPT        | `GPT_MODEL`        | `RRI_GPT_MODEL`         | `gpt-5.5`                  |
| Grok       | `GROK_MODEL`       | `RRI_GROK_MODEL`        | `grok-4.3`                 |
| Gemini     | `GEMINI_MODEL`     | `RRI_GEMINI_MODEL`      | `gemini-3.1-pro-preview`   |
| Perplexity | `PERPLEXITY_MODEL` | `RRI_PERPLEXITY_MODEL`  | `sonar-pro`                |

To bump a seat: change the default in that one constant, **or** set the env
var and restart — no code change, no redeploy. When a provider ships a newer
id, this table + the constant are the only two places to touch.

**Verify on the floor after any bump.** A wrong id 404s at call time, not at
boot. Hit `/ping-swarm` (or a quick round) and confirm each seat responds; if
one fails, flip its `RRI_*_MODEL` env back to a known-good id and restart. Only
`claude-opus-4-8` is verified against a first-party catalog here; the others
track each provider's current docs and may drift — the env override is the
rollback.

## Personas / modes

Two operational modes — selected per session:

- **Functional** — neutral technical personas (`FUNCTIONAL_<MODEL>` prompts)
- **Sovereignty** — Woodland Council lore personas (`SOVEREIGNTY_<MODEL>` prompts)

System-prompt lookup: `get_system_prompt(model)` — called inside each
`call_<model>` function.

## Voice casting

Defined in the `VOICES` dict (`raccoon_swarm_server.py:~120`):

| Model      | ElevenLabs voice_id        | Display name | Label            |
|------------|----------------------------|--------------|------------------|
| Claude     | (George)                   | George       | (narrator)       |
| Grok       | `N2lVS1w4EtoT3dr4eOWO`     | Callum       | Flame-Bearer     |
| Gemini     | (Adam)                     | Adam         | Court Bard       |
| GPT        | (Eric)                     | Eric         | Integrator       |
| Perplexity | `onwK4e9ZLuTAKqWW03F9`     | Daniel       | The Oracle       |

Playback is optional (UI toggle) and uses ElevenLabs REST:
`https://api.elevenlabs.io/v1/text-to-speech/<voice_id>`

## DOCX color coding

Per-model `RGBColor` in `DOCX_COLORS` (`raccoon_swarm_server.py:~960`). Same
palette drives the CSS `--<model>` custom properties in the web UI.

## Toggling models

Each model is independently disableable per session via the UI. The dispatch
loop skips disabled models and grading/synthesis handles the absence.
