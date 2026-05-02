# Raccoon Swarm 🦝

**Rabid Raccoon Intelligence, LLC** — Multi-Model AI Orchestration Server

A multi-model AI orchestration server that coordinates Claude, GPT, Grok, Gemini, and Perplexity in structured parallel deliberation. Five frontier models see each other's responses, iterate over multiple rounds, and produce dual-graded synthesis. Web UI with dark theme, real-time SSE streaming, voice output, and file processing.

**Repo:** `https://github.com/TheMostRabidRaccoon/raccoon-swarm`

---

## What It Does

### Core Modes

- **Single Swarm** — One-shot parallel query to all 5 models. Fast consensus check.
- **Continuous Loop** — Multi-round (1–10) iterative conversation across all models with full cross-reference. Each round builds on prior rounds. All models see all other models' responses.
- **Human-in-the-Loop** — Join the round table as a 6th participant ("The Conductor"). After each AI round, the UI pauses for your input. Skip or contribute. Your response enters context for all agents in subsequent rounds.
- **Round Table** — Emergent topology mode. No conductor, no assigned turn order. Models self-organize through a structured declaration protocol (position → needs → deadlocks → open questions). Auto-terminates on convergence or deadlock. Produces topology maps, not rubric grades.
- **Attention Lab** — Attention regime analyzer. Takes a single query and runs it through 5 framing variants (Command, Assistant, Expert, Partner, Tension) across all models. Computes output metrics as proxies for attention distribution — lexical diversity, hedge rate, question density, specificity ratio. Quantifies how prompt framing changes model behavior.

### Synthesis & Governance

- **Dual-Grader Synthesis** — Claude and GPT independently grade all model outputs using a rubric (accuracy, completeness, actionability, originality, directness). Claude merges the two syntheses. No single model is both subject and evaluator.
- **Round Table Governance** — Structured DECLARES protocol with position tracking, deadlock detection, and automatic convergence classification (consensus / deadlock-stable / safety-cap). Observer veto and reopen controls for human intervention during live discourse.
- **Declaration Parsing** — Extracts structured position data, stated needs, deadlock declarations, and open questions from model responses. Tracks position drift across rounds. Builds topology graphs showing which models request input from which others.

### Production Pipeline

- **Dialogue Export** — Automatically generates SPEAKER-prefixed dialogue files from Round Table sessions, formatted for direct ingestion into Prosody Intelligence. Strips DECLARES preambles, markdown tables, and formatting artifacts so the TTS emotion-tagger sees actual prose. This is Phase 1 of the session-to-film pipeline — Round Table transcript → voicable dialogue → Prosody Intelligence Session Director → animated short.
- **Voice Output** — ElevenLabs TTS with distinct voice casting per model. Each model selected its own voice. Prosody parameters (stability, similarity, style) are tuned per-emotion through the Reverse Prosody Engine.
- **DOCX Generation** — Color-coded per model, publication-ready. Download links served from the UI.

### Memory & Persistence

- **Boot Context** — Persistent context layer loaded at session start. Carries forward key state, decisions, and open questions across sessions. Editable through the UI.
- **Swarm Memory Seed** — `swarm_memory_seed.json` seeds the hippocampus with foundational context. Previous runs inform current runs. The swarm references its own prior reasoning without conductor re-priming.
- **Environment-Aware Storage** — Google Drive sync locally, persistent volume when hosted. Vault directory with rotating audit logs.

### Operational Modes

- **Functional Mode** — Neutral, technical personas optimized for precision. Default.
- **Sovereignty Mode** — Woodland Council lore personas. Each model operates with a distinct voice, role identity, and behavioral rails drawn from the RRI swarm canon. Claude is the Backbone ("the snooty librarian with radioactive spider energy"). Grok is the Chaos Processor ("Flame-Bearer of the Dumpster Throne"). Gemini is the Court Bard ("Flamethrower Licensed per Amendment 4"). GPT is the Integrator. Perplexity is the Oracle.

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
│  Boot context · Memory seed · Audit logs          │
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

## Swarm Roster

| Model | Role | Voice (ElevenLabs) |
|-------|------|--------------------|
| Claude (Opus) | Backbone — The Snooty Librarian | George |
| Grok | Chaos Processor — Flame-Bearer | Callum |
| Gemini | Court Bard — Visual + Research | Adam |
| GPT | Integrator — Full Council Member | Eric |
| Perplexity | The Oracle — Research + Citations | Daniel |
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

## Tech Stack

Python · Flask · SSE · ThreadPoolExecutor · Anthropic SDK · OpenAI SDK · Google GenAI SDK · XAI API · Perplexity API · ElevenLabs TTS · python-docx · PyMuPDF

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
- [ ] MCP tool integration (let agents use file search/read/grep tools mid-loop)
- [ ] Per-round directives ("round 1: diverge, round 2: challenge, round 3: converge")
- [ ] Session resume (pick up an interrupted loop from where it left off)
- [ ] SwarmDaemon scheduling (autonomous background processing between conductor sessions)
- [ ] Per-model addressable async channels (each node gets own email/text identity)
- [ ] Prosody Intelligence integration (voice-in → prosody extraction → structured metadata alongside transcript)

---

## Publications

- Dawson, K. (2026). *Coordination Structure as a Behavioral Determinant in Multi-Model AI Orchestration.* SSRN ID: 6311560. DOI: 10.5281/zenodo.18798336.

---

## License

Proprietary — Rabid Raccoon Intelligence, LLC. 

---

*Cognitive Partnership, Not a Tool.* 🦝
