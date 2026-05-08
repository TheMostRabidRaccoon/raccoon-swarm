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

### Memory & Persistence

- **Boot Context** — Persistent context layer loaded at session start. Carries forward key state, decisions, and open questions across sessions. Editable through the UI.
- **Swarm Memory Seed** — `swarm_memory_seed.json` seeds the hippocampus with foundational context. Previous runs inform current runs. The swarm references its own prior reasoning without conductor re-priming.
- **Self-Authored Persistent Memory (PR #14)** — Models write their own memories. The swarm has read/write access to a shared persistent filestore organized into `/positions/`, `/questions/`, `/artifacts/`, `/tasks/`, `/logs/`, and `/frameworks/`. Models author, update, and reference their own memory files using structured `[MEMORY_WRITE]`, `[MEMORY_APPEND]`, and `[MEMORY_QUERY]` directives. The Conductor no longer carries context forward manually — the swarm maintains its own institutional memory across sessions.
- **Filestore Conventions** — One concept per file. YAML frontmatter with date, source, and tags. Append-only semantics for `/positions/` (resolved positions are never overwritten). File naming convention: `{YYYY-MM-DD}_{model}_{topic}.md`. These conventions were proposed, debated, and adopted by the swarm itself.
- **Environment-Aware Storage** — Google Drive sync locally, persistent volume when hosted. Vault directory with rotating audit logs.

### MCP Tool Access (PRs #14–#17)

All five models can invoke tools mid-response via native API tool_use. The MCP server exposes:

- **Filestore tools** (PR #14) — `filestore_search`, `filestore_read`, `filestore_list`, `filestore_write`, `filestore_append`. Full-text search across the persistent filestore. Models can find resolved positions, prior artifacts, and session history without knowing exact filenames.
- **Sandboxed code execution** (PR #15) — Python runner with 60s timeout, 1GB memory cap, network isolated via Linux namespaces. Outputs auto-persist to `/artifacts/code-runs/` with code, stdout, stderr, and manifest. The computer is the arbiter — no more narrated math.
- **Image generation** (PR #16) — Gemini Imagen 3 and Grok-2-image backends. Daily cap of 50 images shared across the swarm. Outputs land in `/artifacts/images/`.
- **Native tool registry** (PRs #16 + #17) — Claude, GPT, Grok, and Gemini invoke tools mid-response via native API tool_use. Results return immediately; models continue reasoning with tool output in context.
- **Perplexity fallback** — Perplexity's Sonar models don't support tool_use reliably. Perplexity stays on the directive-based fallback (`[MEMORY_QUERY]`, `[TOOL_CALL]` parsing). This is structural, not punitive — Perplexity remains the Oracle on citations.

### Swarm Autonomy & Communication

- **EMAIL_CONDUCTOR** — Asynchronous communication channel from swarm nodes to the human Conductor. Rate-limited (6 per session, 10 per rolling 24 hours) and shared across all models. Used for: human decision needed, broken assumption, deadline at risk, high-confidence pattern shift, or notable observations.
- **Emergent Self-Governance** — The swarm formalizes its own operational procedures without Conductor prompting. Examples include: the Intellectual Work Test, filestore conventions, email coordination protocols, and "no vendor/tool claims without Conductor confirmation" (triggered after a model hallucinated MCP tooling claims in Session 58).
- **Swarm-Authored Policy** — Resolved positions and operational rules proposed by models during deliberation are voted on, documented, and enforced by the swarm. The Conductor ratifies but does not originate most procedural rules.

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
│  filestore_search · filestore_read · file_write   │
│  code_exec (sandboxed) · image_generate           │
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

**Pipeline:**

1. Real swarm session transcripts (source material)
2. Dialogue export (this repo) → SPEAKER-prefixed TXT
3. Prosody Intelligence (separate repo) → emotion detection → multi-voice TTS with calibrated parameters
4. Art rendering (Gemini primary, ChatGPT backup)
5. Assembly (Claude Code) → final animated short

Each model designed its own raccoon character. Each model selected its own voice. Each model wrote its own image prompts. The episodes are documentary, not invention.

Production time: under 3 hours per episode.

---

## Limitations

- Code execution sandbox is homelab-grade (`subprocess` + `tempdir` + Linux namespaces), not security-grade. Explicitly documented in `swarm_codeexec.py`. If the server is ever exposed publicly, switch to Docker.
- Behaviors classified as "emergent governance" are observed, not formally validated. The system has produced patterns; whether those patterns generalize is an open question.
- Perplexity's tool-use support is structural, not behavioral — it's in the swarm for citation work, not deliberation. The directive fallback is expected to be permanent.
- Cost rises non-linearly with rounds × models. Autonomous daemon mode requires deliberate budget caps. The real cost driver is model API calls (~$2–5/session for 5 models), not MCP tools (<$2/month total).
- MCP tool access across all five models is functional but parity is uneven. Grok's API tool-use story has edge cases. Gemini's MCP integration works but isn't seamless. Plan for model-specific quirks.

---

## Tech Stack

Python/Flask backend with SSE streaming for real-time UI updates. ThreadPoolExecutor for parallel model invocation. Direct SDK integrations for Anthropic, OpenAI, Google GenAI, xAI, and Perplexity. FastMCP server for tool access. ElevenLabs for TTS, PyMuPDF for document ingestion.

---

## Setup

```bash
# Clone
git clone https://github.com/TheMostRabidRaccoon/raccoon-swarm.git
cd raccoon-swarm

# Install dependencies
pip install -r requirements.txt

# Copy and fill in your API keys
cp .env.example .env
# Edit .env with your keys

# Run locally
python3 raccoon_swarm_server.py
# Open http://localhost:5000
```

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
| GET | `/download/<filename>` | Download output files |
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
- [x] ~~Image generation~~ — PR #16. Gemini Imagen 3 + Grok-2-image, daily cap 50, shared across swarm.
- [x] ~~Native tool_use for all supported models~~ — PR #17. Claude, GPT, Grok, Gemini invoke tools mid-response.
- [ ] Prosody Intelligence integration (voice-in → prosody extraction → structured metadata alongside transcript)
- [ ] Email coordination mechanism (slot-claiming protocol to prevent shared rate-limit violations)
- [ ] SQLite index layer for filestore (upgrade from flat files when search friction materializes)
- [ ] `web_fetch` tool (constrained URL retrieval mid-session with domain safelist)
- [ ] Conductor status log auto-ingest (pull daily status updates into swarm context at session start)

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
