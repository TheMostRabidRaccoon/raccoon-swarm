# Deploy

Railway-first hosted deployment, with a clean local-dev fallback. Single
web process, single worker, persistent volume.

## Source of truth

- `Procfile`
- `.env.example`
- `raccoon_swarm_server.py` (env-gated storage + auth toggles)
- `README.md` (Deploy section)

## Platform

- Railway (primary). Any platform that honours `Procfile` + `$PORT` will work.
- Python buildpack driven by `runtime.txt` (`python-3.12.8`).

## Process model

- One web process (`Procfile`):
  `gunicorn raccoon_swarm_server:app --worker-class=gthread --workers=1 --threads=8 --timeout=300 --bind=0.0.0.0:$PORT`
- Single worker is deliberate: the Swarm Daemon, in-memory session state,
  and the SSE stream registries are not multi-worker safe.

## Persistent volume

- Mount at `/data` on Railway.
- Set `RRI_STORAGE_DIR=/data` so the server routes memory, logs, outputs,
  ideas, and vault under the volume (`raccoon_swarm_server.py:194`).

## Environment variables

### AI model keys (all required unless the model is toggled off)

| Var                     | Provider      |
|-------------------------|---------------|
| `ANTHROPIC_API_KEY`     | Claude        |
| `OPENAI_API_KEY`        | GPT           |
| `XAI_API_KEY` (or `GROK_API_KEY` fallback) | Grok |
| `GOOGLE_API_KEY`        | Gemini        |
| `PERPLEXITY_API_KEY`    | Perplexity    |

### Voice

| Var                     | Purpose          |
|-------------------------|------------------|
| `ELEVENLABS_API_KEY`    | TTS playback     |

### Auth (hosted only — see `auth.md`)

| Var                     | Purpose                               |
|-------------------------|---------------------------------------|
| `RRI_AUTH_TOKEN`        | UUID4, session cookie value           |
| `RRI_PASSWORD_HASH`     | SHA256 hex of the login password      |

### Hosting flags

| Var                     | Purpose                                                   |
|-------------------------|-----------------------------------------------------------|
| `RAILWAY_ENVIRONMENT`   | Set by Railway to `production`. Also flips storage mode.  |
| `RRI_STORAGE_DIR`       | Override storage root (default `/data` on Railway).       |
| `PORT`                  | Injected by Railway; gunicorn binds to it.                |

### Swarm Daemon (all optional)

| Var                       | Default | Purpose                                  |
|---------------------------|---------|------------------------------------------|
| `SWARM_DAEMON_INTERVAL`   | `21600` | Seconds between autonomous cycles (6h)   |
| `SWARM_DAEMON_COOLDOWN`   | `1800`  | Min gap between sessions (30 min)        |
| `SWARM_DAEMON_MAX_CHAIN`  | `3`     | Max consecutive sessions                 |
| `SWARM_DAEMON_MAX_DAILY`  | `12`    | Hard cap on sessions per 24h             |
| `SWARM_DAEMON_ROUNDS`     | `3`     | Rounds per autonomous session            |

## Deploy checklist

1. Push to GitHub.
2. Link repo in Railway.
3. Set env vars above.
4. Attach persistent volume at `/data`.
5. Set `RRI_STORAGE_DIR=/data`, `RAILWAY_ENVIRONMENT=production`.
6. Set `RRI_AUTH_TOKEN` (any UUID) and `RRI_PASSWORD_HASH` (SHA256 hex).
7. Verify `/memory` returns seed data on first boot.

## Local dev

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in keys
python3 raccoon_swarm_server.py
# http://localhost:5000
```

Local mode skips the login page (auth auto-disabled when no `RRI_AUTH_TOKEN`).
