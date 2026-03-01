# Raccoon Swarm

**Repo:** `https://github.com/TheMostRabidRaccoon/raccoon-swarm` (private)

**Rabid Raccoon Intelligence, LLC** — Multi-Model AI Orchestration Server

## What It Is

A multi-model AI orchestration server that runs Claude, GPT, Grok, Gemini, and Perplexity in a round-table configuration. All models see each other's responses and iterate over multiple rounds. Produces a dual-grader synthesis (Claude + GPT grade independently, Claude merges). Web UI with dark theme, voice playback, file upload, and real-time SSE streaming.

## What It Does

- **Single Swarm** — One-shot parallel query to all 5 models
- **Continuous Loop** — Multi-round (1-10) iterative conversation across all models with full cross-reference
- **Human-in-the-Loop** — Join the round table as a 6th participant ("The Conductor"). After each AI round, the UI pauses for your input. Skip or contribute. Your response gets included in context for all agents in subsequent rounds.
- **Dual-Grader Synthesis** — Claude and GPT independently grade all model outputs using a rubric (accuracy, completeness, actionability, originality, directness), then Claude merges the two syntheses
- **Two Operational Modes** — Functional (neutral/technical personas) and Sovereignty (Woodland Council lore personas)
- **Voice Output** — ElevenLabs TTS with distinct voice casting per model (George, Callum, Adam, Eric, Daniel)
- **File Processing** — Text files, PDFs (via PyMuPDF), and images (sent to vision APIs)
- **Model Toggles** — Enable/disable any model per session
- **Output** — DOCX (color-coded per model) + JSON logs, with download links
- **Idea Capture** — Quick-save ideas with timestamps
- **Password-Protected Auth** — Login page for hosted deployment (auto-disabled locally)
- **Environment-Aware Storage** — Google Drive locally, persistent volume when hosted

## Tech Stack

Python, Flask, SSE, ThreadPoolExecutor, Anthropic/OpenAI/Google GenAI/XAI/Perplexity SDKs, ElevenLabs TTS, python-docx, PyMuPDF

## Swarm Roster

| Model | Role | Voice |
|-------|------|-------|
| Claude (Opus) | Backbone — The Snooty Librarian | George |
| Grok | Chaos Processor — Flame-Bearer | Callum |
| Gemini | Visual + Research — Court Bard | Adam |
| GPT | Integrator — Under Supervision | Eric |
| Perplexity | Research — The Oracle | Daniel |
| Human (optional) | The Conductor | - |

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

## Future Add-Ons / Pending

- [ ] Google Drive API upload (replace local FUSE mount for hosted output sync)
- [ ] Loop auto-termination (detect convergence across rounds, stop early)
- [ ] Transcript search (persistent searchable history of all loop sessions)
- [ ] MCP tool integration (let agents use file search/read/grep tools mid-loop)
- [ ] Per-round directives ("round 1: diverge, round 2: challenge, round 3: converge")
- [ ] Session resume (pick up an interrupted loop from where it left off)
- [ ] Swarm-to-swarm protocol (formalized cross-model routing with Claude as hub conductor)

## About the Builder

**Who I am**

Builder. I make AI systems that solve real problems for real people — not demos, not prototypes, working products.

**What I build**

- **Legal tech** — AI tools that help legal professionals work faster without losing accuracy
- **Sports analytics** — data-driven systems for competitive edges
- **Prosody & speech** — teaching machines how humans actually talk — rhythm, tone, emphasis
- **AI agent swarms** — multi-agent systems that coordinate to handle complex workflows

I build the systems you already wish existed.

---

*Rabid Raccoon Intelligence, LLC — Cognitive Partnership, Not a Tool*
