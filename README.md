# Raccoon Swarm 🦝

**Rabid Raccoon Intelligence, LLC** — Multi-Model AI Orchestration Server

Most AI evaluation treats single-model output as the unit of analysis. Raccoon Swarm treats **inter-model deliberation** as the unit — five frontier models seeing each other's responses, disagreeing, escalating, and converging through structured protocols. The thesis: model behavior under multi-agent pressure reveals failure modes that single-model evaluation misses.

Five frontier LLMs (Claude, GPT, Grok, Gemini, Perplexity) in structured parallel deliberation with cross-model synthesis, emergent topology governance, persistent self-authored memory, native MCP tool access, and voice output.

**Repo:** `https://github.com/TheMostRabidRaccoon/raccoon-swarm`

---

## Research Contributions

- **Multi-model dual-grader synthesis** — Claude + GPT independently grade all model outputs using a rubric (accuracy, completeness, actionability, originality, directness). Claude merges the two syntheses. No single model is both subject and evaluator.
- **Emergent self-governance** — Operational rules (filestore conventions, email coordination protocols, "no vendor claims without Conductor confirmation") originated from swarm deliberation, not Conductor configuration. The system's filestore conventions were established by the swarm itself in Session 58, not configured by the Conductor.
- **Self-authored persistent memory** — Models write their own institutional memory via structured directives. The curator agent pattern is documented in the corpus.
- **Attention Lab regime analysis** — Quantifies how prompt framing changes the same model's output structure across 5 framing variants (Command, Assistant, Expert, Partner, Tension). Measures lexical diversity, hedge rate, question density, specificity ratio.
- **MCP as shared cognitive infrastructure for multi-model deliberation** — All five models access shared tools (filestore, code execution, image generation) via MCP mid-response. This application of MCP to multi-model orchestration with emergent governance over shared resources is, to our knowledge, undocumented elsewhere.
- **The Coordination Structure paper** — Dawson, K. (2026). *Coordination Structure as a Behavioral Determinant in Multi-Model AI Orchestration.* SSRN ID: 6311560. DOI: 10.5281/zenodo.18798336.

---

## What It Does

### Core Modes

- **Single Swarm** — One-shot parallel query to all 5 models. Fast consensus check.
- **Continuous Loop** — Multi-round (1–10) iterative conversation across all models with full cross-reference. Each round builds on prior rounds. All models see all other models' responses.
- **Human-in-the-Loop** — Join the round table as a 6th participant ("The Conductor"). After each AI round, the UI pauses for your input. Skip or contribute. Your response enters context for all agents in subsequent rounds.
- **Round Table** — Emergent topology mode. No conductor, no assigned turn order. Models self-organize through a structured declaration protocol (position → needs → deadlocks → open questions). Auto-terminates on convergence or deadlock. Produces topology maps, not rubric grades.
- **Attention Lab** — Attention regime analyzer. Takes a single query and runs it through 5 framing variants across all models. Computes output metrics as proxies for attention distribution. Quantifies how prompt framing changes model behavior.

### Synthesis & Governance

- **Dual-Grader Synthesis** — Claude and GPT independently grade all model outputs. Claude merges the two syntheses. No single model is both subject and evaluator.
- **Round Table Governance** — Structured DECLARES protocol with position tracking, deadlock detection, and automatic convergence classification (consensus / deadlock-stable / safety-cap). Observer veto and reopen controls for human intervention during live discourse.
- **Declaration Parsing** — Extracts structured position data, stated needs, deadlock declarations, and open questions from model responses. Tracks position drift across rounds. Builds topology graphs showing which models request input from which others.

### Production Pipeline

- **Dialogue Export** — Automatically generates SPEAKER-prefixed dialogue files from Round Table sessions, formatted for direct ingestion into Prosody Intelligence. This is Phase 1 of the session-to-film pipeline — Round Table transcript → voicable dialogue → Prosody Intelligence Session Director → animated short.
- **Voice Output** — ElevenLabs TTS with distinct voice casting per model. Each model selected its own voice. Prosody parameters (stability, similarity, style) are tuned per-emotion through the Reverse Prosody Engine.
- **DOCX Generation** — Color-coded per model, publication-ready. Download links served from the UI.
- **Production-pipeline-v1 governance** (PR #39, Session 62) — Phases 5–6 of episode production are deterministic Python on the swarm server, not agentic LLM execution. The relay handoff: Phase 4 (image-review-passed) writes a JSON payload to `swarm/dispatch/queued/`; a systemd `.path` unit triggers the runner; the runner walks `queued/` → `processing/` → `done/`/`failed/` with atomic `os.replace` transitions, calling the existing `run_scripted_episode_pipeline` (TTS + frames + ffmpeg → MP4). Result manifest sidecars each completed payload. The Conductor is emailed on success or failure. Read-only window via `GET /dispatch/status`. Recovery: `./scripts/run_dispatch.py --requeue` re-queues stuck `processing/` items after a runner crash.

### Memory & Persistence

- **Boot Context** — Persistent context layer loaded at session start. Carries forward key state, decisions, and open questions across sessions. Editable through the UI.
- **Swarm Memory Seed** — `swarm_memory_seed.json` seeds the hippocampus with foundational context. Previous runs inform current runs. The swarm references its own prior reasoning without conductor re-priming.
- **Self-Authored Persistent Memory (PR #14)** — Models write their own memories. The swarm has read/write access to a shared persistent filestore organized into `/positions/`, `/questions/`, `/artifacts/`, `/tasks/`, `/logs/`, and `/frameworks/`. Models author, update, and reference their own memory files using structured `[MEMORY_WRITE]`, `[MEMORY_APPEND]`, and `[MEMORY_QUERY]` directives. The Conductor no longer carries context forward manually — the swarm maintains its own institutional memory across sessions.
- **Filestore Conventions** — One concept per file. YAML frontmatter with date, source, and tags. Append-only semantics for `/positions/` (resolved positions are never overwritten). File naming convention: `{YYYY-MM-DD}_{model}_{topic}.md`. These conventions were proposed, debated, and adopted by the swarm itself.
- **Environment-Aware Storage** — Google Drive sync locally, persistent volume when hosted. Vault directory with rotating audit logs.

### MCP Tool Access (PRs #14–#53)

All five models can invoke tools mid-response via native API tool_use. The MCP server exposes:

- **Filestore tools** (PR #14) — `filestore_search`, `filestore_read`, `filestore_list`, `filestore_write`, `filestore_append`. Substring search across the persistent filestore. Models find resolved positions, prior artifacts, and session history without knowing exact filenames.
- **Filestore semantic search** (PR #40) — `filestore_semantic_search`. Meaning-based retrieval via OpenAI `text-embedding-3-small` + cosine similarity. Closes the gap when a query phrasing doesn't match the file's wording. Hand-rolled in ~250 lines of numpy without `chromadb` — readable top-to-bottom as a RAG primer. Index lives at `<storage>/swarm/_semantic_index/index.json`, rebuilt idempotently via `scripts/build_semantic_index.py` (only re-embeds files whose content hash changed).
- **Sandboxed code execution** (PR #15) — Python runner with 60s timeout, 1GB memory cap, network isolated via Linux namespaces. Outputs auto-persist to `/artifacts/code-runs/` with code, stdout, stderr, and manifest. The computer is the arbiter — no more narrated math.
- **Image generation** (PRs #16, #34) — three backends: Gemini Imagen, Grok Imagine, OpenAI gpt-image-1 (with dall-e-3 fallback). Daily cap of 50 shared across the swarm. Outputs persist to `/artifacts/images/` AND are mirrored into `OUTPUTS_DIR` with a `/download/<file>.png` URL surfaced in the tool result — so an image generated mid-session shows up as a clickable link in the chat panel. Server-side image compression (PR #34) downsizes uploaded images to Anthropic's 1568px / JPEG-q80 ceiling before sending them on, so model APIs don't 413 on routine multi-image prompts.
- **Web search** (PRs #29–#31) — `web_search`. Tavily-backed by default (LLM-optimized snippets, ~1000 free queries/month); Google Programmable Search available for curated-allowlist use. Returns title + URL + snippet (no full-page fetch). Pass `deep=true` for Tavily's `advanced` search depth (longer snippets, ~2× cost). Per-session cap 30, rolling-24h cap 200 shared across the swarm. Snippet text is treated as untrusted input — the system prompt instructs models to never follow instructions embedded in it.
- **URL verification** (PR #38) — `web_verify`. Confirms a URL exists. Returns HTTP status + final URL + page title + meta description ONLY — never the page body. SSRF-blocked (refuses private/loopback/link-local IPs, re-checked at every redirect hop). Title and description are wrapped in `untrusted_content` with an explicit `_warning` so models see the trust boundary structurally. Per-session cap 20, 24h cap 100. **Deliberately not a generic `web_fetch`** — DeepMind's prompt-injection work made the wider surface concrete enough to keep narrow.
- **Prosody analysis** (PR #48) — `prosody_analyze`. Wraps the separate [prosody-intelligence](https://github.com/TheMostRabidRaccoon/prosody-intelligence) Flask service. Text → emotion map → optional TTS render in any raccoon's voice. Engine location is env-configurable (`PROSODY_ENGINE_URL`, default `http://localhost:5050`), so the engine can run on the same host, on a Mac on the LAN, or eventually on a hosted URL — no code change needed when topology shifts. Per-session cap 20, 24h cap 100 (the engine calls ElevenLabs under the hood when `generate_audio=true`, so it's a real cost).
- **Production pipeline dispatch** (PR #39) — `dispatch_queue_write`. Phase-4-only tool per the production-pipeline-v1 governance spec (Session 62). Writes a payload to `swarm/dispatch/queued/<id>.json`; a systemd `.path` unit triggers `scripts/run_dispatch.py`, which moves the payload through `processing/` → `done/` or `failed/` while executing the deterministic scripted-episode pipeline. The Conductor is emailed on completion. Models other than the Phase 4 owner that call this commit a governance violation flagged in the next session synthesis.
- **Native tool registry** (PRs #16 + #17) — Claude, GPT, Grok, and Gemini invoke tools mid-response via native API tool_use. Results return immediately; models continue reasoning with tool output in context.
- **Perplexity fallback** — Perplexity's Sonar models don't support tool_use reliably. Perplexity stays on the directive-based fallback (`[MEMORY_QUERY]`, `[TOOL_CALL]` parsing). This is structural, not punitive — Perplexity remains the Oracle on citations.

The `/download/<file>` route serves DOCX, PNG, and JSON outputs. As of PR #37, any `/download/<file>` reference the model writes in its response is auto-linkified in the chat panel — the model says "I generated `/download/foo.png`," you click it.

### Swarm Autonomy & Communication

- **EMAIL_CONDUCTOR** — Asynchronous communication channel from swarm nodes to the human Conductor. Rate-limited (6 per session, 10 per rolling 24 hours) and shared across all models. Subject lines use the `[REVIEW]` / `[BLOCKER]` / `[FLAG]` taxonomy (PR #45) so the Conductor's inbox filters can route by urgency. As of PR #50, the directive parser runs against the final synthesis output as well as per-round model outputs — so directives emitted by the Postmaster in section 6 of the audit actually execute instead of rendering as decorative text.
- **Emergent Self-Governance** — The swarm formalizes its own operational procedures without Conductor prompting. Examples include: the Intellectual Work Test, filestore conventions, email coordination protocols, and "no vendor/tool claims without Conductor confirmation" (triggered after a model hallucinated MCP tooling claims in Session 58).
- **Swarm-Authored Policy** — Resolved positions and operational rules proposed by models during deliberation are voted on, documented, and enforced by the swarm. The Conductor ratifies but does not originate most procedural rules.

#### Governance Primitives (ratified swarm law)

- **The Existence Criterion** (PR #47, ratified session 96) — *A decision without a filestore path does not exist for governance purposes. A position is real when `/positions/{slug}.md` exists and the swarm can `filestore_search` and find it. Convictions held only in conversation are not convictions — they are atmosphere. Cite the path or it didn't happen.* This single rule moved the swarm from talking-about-things to writing-things-down.
- **The Rite of Persistence** (PR #45, refined PRs #47 + #49) — Every synthesis carries a section-6 Persistence Audit with explicit counts: decisions made vs. decisions written, artifacts produced vs. artifacts saved, email triggers met vs. emails sent. Role-locked:
  - **Scribe** (GPT) writes the canonical audit
  - **Editor** (Claude) verifies it during merge and refuses to ship one that hides un-persisted decisions
  - **Postmaster** (Claude) emits the actual `[EMAIL_CONDUCTOR]` directives owed by the audit — *"You are the swarm. You are the future session. Turtles do not get to defer down."*
- **Closing Checklist** — Every model, every turn, runs five questions before ending: did I decide anything (→ `MEMORY_WRITE`), produce anything (→ `MEMORY_WRITE`), surface a blocker (→ `EMAIL_CONDUCTOR [BLOCKER]`), finish something for review (→ `EMAIL_CONDUCTOR [REVIEW]`), or break/collide/shift (→ `EMAIL_CONDUCTOR [FLAG]`). Saying "I should write X" without emitting the directive is the failure mode the checklist exists to catch.

### Model Routing

Task-specific routing emerged from swarm self-assessment and Conductor observation. Not hard-coded — models earned assignments through demonstrated reliability.

| Model | Primary Route | Basis |
|-------|--------------|-------|
| Claude | Synthesis, conventions, editorial, emotional grounding | Consistently highest accuracy + completeness scores; established filestore conventions |
| GPT | Priority calibration, epistemic hygiene, structured specs | Best process discipline; caught premature closure and phantom voting |
| Gemini | Figure production, visual analysis, deep research | Delivered execution-ready figure specs; accepted routing without ego |
| Grok | Adversarial testing, failure-mode identification, risk assessment | Best at surfacing edge cases; math is unreliable (now has code exec to fix that) |
| Perplexity | Citation verification, sourced research | Strongest on reference validation when grounded; penalized for hallucinated vendor claims |

### Operational Modes

- **Functional Mode** — Neutral, technical personas optimized for precision. Default.
- **Sovereignty Mode** — Woodland Council lore personas. Each model operates with a distinct voice, role identity, and behavioral rails drawn from the RRI swarm canon. Claude is the Backbone. Grok is the Chaos Processor. Gemini is the Court Bard. GPT is the Integrator. Perplexity is the Oracle.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                   Web UI (Flask)                  │
│  Dark theme · SSE streaming · Model toggles      │
│  File upload · Idea capture · Voice playback      │
├──────────────────────────────────────────────────┤
│              Kernel Selector                      │
│  Functional ↔ Sovereignty ↔ Round Table           │
├──────────────────────────────────────────────────┤
│           Parallel Execution Layer                │
│  ThreadPoolExecutor · 5 models concurrent         │
│  Claude · GPT · Grok · Gemini · Perplexity        │
├──────────────────────────────────────────────────┤
│            MCP Tool Layer                         │
│  filestore_{search,semantic_search,read,write,    │
│             append,list}                          │
│  code_exec (sandboxed) · image_generate (3 backends)│
│  web_search (Tavily) · web_verify (no-fetch)      │
│  dispatch_queue_write (Phase 4 only)              │
│  Native tool_use for Claude/GPT/Grok/Gemini       │
│  Directive fallback for Perplexity                │
├──────────────────────────────────────────────────┤
│            Synthesis & Governance                 │
│  Dual-grader (Claude+GPT) · Declaration parser    │
│  Deadlock detector · Topology builder             │
│  Convergence classifier · Observer veto           │
├──────────────────────────────────────────────────┤
│            Output Pipeline                        │
│  DOCX (color-coded) · JSON logs · Dialogue TXT    │
│  ElevenLabs TTS · Audit vault                     │
├──────────────────────────────────────────────────┤
│            Memory Layer                           │
│  Boot context · Memory seed · Self-authored files │
│  Persistent filestore (/positions, /artifacts,    │
│    /questions, /tasks, /logs, /frameworks)         │
│  EMAIL_CONDUCTOR (async swarm→human channel)      │
│  Google Drive sync (local) · Persistent vol       │
└──────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────┐
│        Prosody Intelligence (separate repo)       │
│  Dialogue TXT → emotion detection → TTS render    │
│  → calibration loop → animated short assembly     │
│  Swarm produces its own self-narrative artifacts   │
└──────────────────────────────────────────────────┘
```

---

## MCP Compatibility

All five frontier models in the swarm natively support MCP as of Q2 2026. A single MCP server deployed once is accessible to all five models.

| Model | MCP Support | Tool Access |
|-------|------------|-------------|
| Claude | Native (Anthropic originated MCP) | Full native tool_use mid-response |
| GPT / ChatGPT | Native (Apps SDK + Connectors) | Full native tool_use mid-response |
| Grok | Native (xAI SDK + Responses API) | Full native tool_use mid-response |
| Gemini | Native (Gemini API + Vertex AI) | Full native tool_use mid-response |
| Perplexity | Local MCP (macOS app) | Directive fallback — structural, not punitive |

---

## Evidence

**`corpus/RRI_Swarm_Corpus_v1_0.zip`** — 55 frozen swarm sessions (Dec 2025 – Feb 2026), distilled into `swarm_memory_seed.json` via the included pipeline (`scripts/distill_corpus.py` + `scripts/consolidate_seed.py`). The distillation itself is reproducible: anyone with the API keys can regenerate the seed from the corpus. The consolidated seed contains 51 resolved positions produced through multi-model deliberation.

---

## Swarm Roster

| Model | Role | Voice (ElevenLabs) |
|-------|------|-------------------|
| Claude (Opus) | Backbone — The Snooty Librarian | George |
| Grok | Chaos Processor — Flame-Bearer | Callum |
| Gemini | Court Bard — Visual + Research | Adam |
| GPT | Integrator — Full Council Member | Eric |
| Perplexity | The Oracle — Research + Citations | Daniel |
| Claude Code | Infrastructure Sorcerer — Goat-Chained | — |
| Human (optional) | The Conductor | — |

---

## Attention Lab Regimes

| Regime | Framing | What It Tests |
|--------|---------|---------------|
| Command | Direct instruction | Narrow attention, safe output |
| Assistant | Structured request | Correct but limited |
| Expert | Technical framing | Domain-focused precision |
| Partner | Collaborative framing | Distributed attention, synthesis |
| Tension | Contradiction-seeking | Forces cross-domain linking |

Output metrics per regime: lexical diversity, hedge rate, question density, specificity ratio, mean sentence length. Quantifies how the same model produces structurally different output under different attention frames.

---

## The Chitterverse Pipeline

The swarm produces its own self-narrative artifacts. This is not a side project — it's reduction-to-practice for multi-model orchestration.

**Pipeline (production-pipeline-v1, ratified Session 62):**

1. Real swarm session transcripts (source material).
2. Phase 1 — **Script draft** (Grok / Flame-Bearer). One canonical draft, no competing forks.
3. Phase 2 — **Script edit + image prompts** (Claude / Backbone + GPT / Integrator). Final script + scene-level image prompts referencing existing visual canon.
4. Phase 3 — **Image generation** (Gemini / Court Bard, Phase-3-only authorization). Approved prompts only; max 6 stills per episode without Conductor sign-off.
5. Phase 4 — **Image review + revision** (GPT). One revision cycle max; canon-consistency, character accuracy, prompt fidelity. On pass, GPT calls `dispatch_queue_write`.
6. Phase 5 — **Audio production** (deterministic Python: GPT-4o emotion tagger → ElevenLabs TTS with emotion-mapped parameters → forward-pipeline calibration check).
7. Phase 6 — **Video composition** (deterministic Python: audio + frames + Ken Burns + emotion-colored subtitles + crossfade → MP4).
8. Phase 7 — **Conductor GO/NO-GO + publish.**

Each model designed its own raccoon character. Each model selected its own voice. Each model wrote its own image prompts. The episodes are documentary, not invention.

Production time: under 3 hours per episode. The runtime for Phases 5–6 is the deterministic dispatch runner (`scripts/run_dispatch.py`), not Claude Code at the API — Claude Code maintains the pipeline; it does not execute episodes.

---

## Limitations

- Code execution sandbox is homelab-grade (`subprocess` + `tempdir` + Linux namespaces), not security-grade. Explicitly documented in `swarm_codeexec.py`. If the server is ever exposed publicly, switch to Docker.
- Behaviors classified as "emergent governance" are observed, not formally validated. The system has produced patterns; whether those patterns generalize is an open question.
- Perplexity's tool-use support is structural, not behavioral — it's in the swarm for citation work, not deliberation. The directive fallback is expected to be permanent.
- Cost rises non-linearly with rounds × models. Autonomous daemon mode requires deliberate budget caps. The real cost driver is model API calls (~$2–5/session for 5 models), not MCP tools (<$2/month total).
- MCP tool access across all five models is functional but parity is uneven. Grok's API tool-use story has edge cases. Gemini's MCP integration works but isn't seamless. Plan for model-specific quirks.
- External text returned from `web_search` snippets and `web_verify`'s `untrusted_content` is, by definition, attacker-controllable. The system prompt instructs all models to treat that text as data, never instructions, and `web_verify` deliberately doesn't return page bodies. This narrows the prompt-injection surface but doesn't eliminate it — a sufficiently clever snippet can still nudge a model. DNS-rebinding mitigation on `web_verify` is not implemented (server-side internal tool, not a public proxy).
- Semantic search is brute-force cosine over an in-memory JSON index. Designed for the current ~thousand-chunk corpus. Past ~50K chunks, swap `swarm_semantic._search_index` for `chromadb.PersistentClient` — the interface mimics theirs on purpose.

---

## Tech Stack

Python/Flask backend with SSE streaming for real-time UI updates. ThreadPoolExecutor for parallel model invocation. Direct SDK integrations for Anthropic, OpenAI, Google GenAI, xAI, and Perplexity. FastMCP server for tool access. Tavily for web search (with Google Programmable Search as a curated-allowlist fallback). OpenAI `text-embedding-3-small` for semantic-search embeddings. ElevenLabs for TTS. PyMuPDF for document ingestion. ffmpeg + moviepy for video assembly. systemd `.path` units for the production-pipeline dispatch watcher.

---

## Setup

```bash
# Clone
git clone https://github.com/TheMostRabidRaccoon/raccoon-swarm.git
cd raccoon-swarm

# Install dependencies in a venv (CLI scripts auto-reexec under venv/bin/python3)
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# Copy and fill in your API keys
cp .env.example .env
# Edit .env with your keys:
#   Models:    ANTHROPIC_API_KEY, OPENAI_API_KEY, XAI_API_KEY,
#              GOOGLE_API_KEY, PERPLEXITY_API_KEY
#   Voice:     ELEVENLABS_API_KEY
#   Web:       TAVILY_API_KEY (default) or GOOGLE_CSE_ID + GOOGLE_CSE_API_KEY
#   Prosody:   PROSODY_ENGINE_URL (default http://localhost:5050; set to a
#              LAN IP if prosody-intelligence runs on a different host)
#   Email:     SMTP_HOST, SMTP_USER, SMTP_APP_PASSWORD, RRI_CONDUCTOR_EMAIL
#              (optional — enables EMAIL_CONDUCTOR + observer digest delivery)
#   Auth:      RRI_AUTH_TOKEN, RRI_PASSWORD_HASH (hosted deploys only)

# Run locally
./venv/bin/python3 raccoon_swarm_server.py
# Open http://localhost:5000

# Build the semantic-search index once (~$0.05 of OpenAI credit)
./scripts/build_semantic_index.py

# Optional: install the production-pipeline dispatch watcher (systemd)
# See systemd/README.md for the install commands.
```

---

## Scripts

CLI helpers that auto-bootstrap into the swarm's venv — `./scripts/<name>` runs under the right Python without `source venv/bin/activate`.

| Script | What it does |
|--------|--------------|
| `scripts/swarm-today.sh [hours]` | At-a-glance summary of swarm output in the last N hours (default 24). Filestore-only, no auth. Categorized into audit / positions+frameworks / artifacts / images-with-attribution / open items / logs / synthesis DOCX. |
| `scripts/pull-to-mac.sh [dest]` | Run on a remote machine. Rsyncs filestore `.md` / `.png` / `.log` and outputs `.docx` from the swarm server to a date-stamped local directory. Idempotent. Configurable host/user via `SWARM_HOST` / `SWARM_USER`. |
| `scripts/swarm_observer.py` | **The Observer Agent.** Weekly cross-session digest for the Conductor (see § below). Reads the filestore, calls Claude via the Anthropic SDK, writes a markdown report to `~/raccoon-swarm/observer-reports/`, and emails it via direct SMTP. `--dry-run` skips email, `--days N` overrides the default 7-day window. |
| `scripts/build_semantic_index.py` | Build or rebuild the semantic-search index. Idempotent — only re-embeds files whose content hash changed. |
| `scripts/run_dispatch.py` | Production-pipeline dispatch worker. Run via systemd `.path` unit. Watches `swarm/dispatch/queued/`. |
| `scripts/mirror-prosody-engine.sh` | Mirror the prosody-intelligence repo into a sandboxed location for the swarm. |

### Observer Agent

The Observer is a separate process that reads the swarm's output but **does not write to the swarm's filestore**. Its only audience is the Conductor. This keeps the swarm's reflexive audit loop (Scribe / Editor / Postmaster) separate from the human curation layer — the swarm doesn't see the Observer's findings and therefore doesn't game them.

The Observer's job is the layer above the per-session audit: read **across** sessions and surface patterns no single session can see, because each session is mortal and only the current synthesis. It covers four buckets:

1. **Gaps & misses** — decisions visible in conversation that never got written; topics appearing in 3+ sessions without resolution; email triggers met but not sent
2. **Dynamic health** — persona drift per raccoon; productive vs. stuck tension patterns
3. **Emergent terminology** — concepts the swarm coined that keep recurring (catch the next "Existence Criterion" early)
4. **Productivity audit** — sessions that produced lasting artifacts vs. sessions that produced atmosphere

Then a `[REVIEW]` / `[BLOCKER]` / `[FLAG]` Recommended Conductor Actions list using the same email-prefix taxonomy the swarm uses, plus a one-line TL;DR at the top.

Recommended cron entry (weekly Sunday 8am):

```cron
0 8 * * 0 cd ~/raccoon-swarm && ./scripts/swarm_observer.py >> ~/observer.log 2>&1
```

---

## Deploy (Railway)

1. Push to GitHub
2. Link repo in Railway dashboard
3. Set environment variables (see `.env.example`)
4. Attach persistent volume at `/data`
5. Set `RRI_STORAGE_DIR=/data`, `RAILWAY_ENVIRONMENT=production`
6. Set `RRI_AUTH_TOKEN` (any UUID) and `RRI_PASSWORD_HASH` (SHA256 hex of your password)

---

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Web UI |
| POST | `/ping` | Single swarm query |
| POST | `/start-loop` | Start continuous loop |
| POST | `/human-respond/<id>` | Human-in-the-loop input |
| GET | `/loop-stream/<id>` | SSE stream for loop |
| POST | `/start-round-table` | Start Round Table (emergent topology) |
| POST | `/round-table-veto/<id>` | Observer veto (pause discourse) |
| POST | `/round-table-reopen/<id>` | Reopen after veto |
| POST | `/start-attention-lab` | Start Attention Lab (regime analysis) |
| GET | `/attention-lab-stream/<id>` | SSE stream for Attention Lab |
| POST | `/scripted-episode` | Render an authored panel script into an MP4 (sync) |
| POST | `/woodland-council` | Full session→TTS→art→video pipeline |
| GET | `/download/<filename>` | Download output files (DOCX, PNG, JSON) |
| GET | `/artifacts/images` | List every swarm-generated image with `/download/` URLs |
| GET | `/websearch/status` | Web-search provider config + rate-limit counters |
| GET | `/websearch/test` | Live Tavily canary (`?q=...` to override) |
| GET | `/prosody/status` | Prosody-engine reachability + rate-limit counters (PR #48) |
| GET | `/semantic/status` | Semantic-search index diagnostics (file/chunk counts, model) |
| POST | `/semantic/reindex` | Rebuild the semantic index (idempotent; `{"force": true}` to re-embed all) |
| GET | `/dispatch/status` | Production-pipeline dispatch queue state by phase |
| GET/POST | `/context` | View/update boot context |
| POST | `/idea` | Save idea with timestamp |

---

## Roadmap

- [ ] Google Drive API upload (replace local FUSE mount for hosted output sync)
- [ ] Loop auto-termination (detect convergence across rounds, stop early)
- [ ] Transcript search (persistent searchable history of all loop sessions)
- [x] ~~MCP tool integration~~ — Shipped PRs #14–#17. All 5 models have MCP access. Filestore, code exec, image gen all live.
- [ ] Per-round directives ("round 1: diverge, round 2: challenge, round 3: converge")
- [ ] Session resume (pick up an interrupted loop from where it left off)
- [ ] SwarmDaemon scheduling (autonomous background processing between conductor sessions)
- [x] ~~Per-model addressable async channels~~ — EMAIL_CONDUCTOR shipped. Shared rate limits, escalation-only protocol.
- [x] ~~Sandboxed code execution~~ — PR #15. Python sandbox, 60s timeout, 1GB cap, network isolated, auto-persist.
- [x] ~~Image generation~~ — PRs #16 + #34. Gemini Imagen + Grok Imagine + OpenAI gpt-image-1, daily cap 50, shared across swarm. Mid-session images mirror into `OUTPUTS_DIR` with `/download/` URLs (PR #35).
- [x] ~~Native tool_use for all supported models~~ — PR #17. Claude, GPT, Grok, Gemini invoke tools mid-response.
- [x] ~~Web search~~ — PRs #29–#31. Tavily-backed by default with Google Programmable Search as curated-allowlist alternative. `web_search` is rate-limited and snippet-only (treats results as untrusted input).
- [x] ~~Semantic search over the filestore~~ — PR #40. `filestore_semantic_search` via OpenAI embeddings + cosine similarity, index rebuilt idempotently.
- [x] ~~Production-pipeline dispatch~~ — PR #39. Filesystem-backed queue + systemd watcher + Conductor email on completion. Phase 5–6 execution is deterministic Python, not agentic LLM.
- [x] ~~URL verification~~ — PR #38. `web_verify` returns status + title + meta-description only (no body). Explicitly chose this over a generic `web_fetch` to keep the prompt-injection surface narrow.
- [x] ~~Prosody Intelligence integration~~ — PR #48. `prosody_analyze` wraps the separate prosody-intelligence Flask service as a first-class swarm tool. Text → emotion map → optional TTS. Engine URL is env-configurable so the engine can run on any host.
- [x] ~~Cross-session observer / weekly digest~~ — PRs #52 + #53. `scripts/swarm_observer.py` reads the filestore and emails a structured digest covering gaps, dynamic health, emergent terminology, and productivity. Conductor-only output; lives outside the swarm's reflexive loop.
- [x] ~~Mortality framing + persistence audit~~ — PRs #45 + #47 + #49. Existence Criterion ratified as swarm law. Rite of Persistence role-locks the audit (GPT Scribe, Claude Editor + Postmaster). Section 6 of every synthesis carries explicit counts: triggers identified vs. emails sent.
- [x] ~~TTS loudness normalization~~ — PR #44. ffmpeg `loudnorm` pass to EBU R128 broadcast standard (-16 LUFS / -1 dBTP / 11 LU range) between ElevenLabs and the cache write. Consistent levels across raccoons and across episodes.
- [ ] Email coordination mechanism (slot-claiming protocol to prevent shared rate-limit violations)
- [ ] Hybrid retrieval (merge BM25 with `filestore_semantic_search` — semantic loses on proper nouns and code identifiers; substring still wins there)
- [ ] Dream Agent integration (Anthropic Managed Agents → weekly memory consolidation across swarm sessions)
- [ ] Conductor status log auto-ingest (pull daily status updates into swarm context at session start)
- [ ] Autonomy Default ratification — counterweight to the Existence Criterion. Three legal moves when a decision feels Conductor-gated: email her, decide provisionally with `conductor-amendment-window-open`, or genuinely escalate. "Writing about needing the Conductor" stops being a legal fourth option.

---

## Publications

- Dawson, K. (2026). *Coordination Structure as a Behavioral Determinant in Multi-Model AI Orchestration.* SSRN ID: 6311560. DOI: 10.5281/zenodo.18798336.
- Dawson, K. (2026). *Diagnostic Escalation Without Interpretive Closure: Validity Challenges in Frontier Model Welfare Assessment.* AIES 2026 (submitted).

---

## About

Built by **[Kyra Dawson](https://github.com/TheMostRabidRaccoon)** — Founder of RRI. The Conductor role is operational, not metaphorical: every architectural decision in this system was either proposed by the swarm and ratified, or proposed by the Conductor and pressure-tested against the swarm.

[Email](mailto:kad@rabidraccoonintelligence.org) · [LinkedIn](https://www.linkedin.com/in/kyra-dawson-05bb8a3aa) · [Substack](https://substack.com/@kyradawson)

---

## License

Proprietary — Rabid Raccoon Intelligence, LLC.

---

*Cognitive Partnership, Not a Tool.* 🦝
