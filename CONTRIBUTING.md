# Contributing

**How to change this repo — human or model — without creating ghosts.**

## The Existence Criterion (this is law, not prose)

> **Only artifacts verifiable by `filestore_search` or direct repository
> existence are real. Chat claims, planned writes, and decorative
> `[MEMORY_WRITE]` blocks are not evidence.** The closer computes
> `persistence_gap` from *verified* paths; unverified write-claims count
> against it.

Announcing a write is not a write. Saying "I've saved it to
`positions/foo.md`" creates nothing — only an actual `[MEMORY_WRITE: …]`
directive (or a real file in a commit) does. This is enforced mechanically:
`swarm_closer.find_phantom_claims()` checks the real floor for every claimed
path and names the ones that aren't there. If you claim it, land it, then
verify it exists. No exceptions, including in reviews and audits.

## Local run

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in what you need; see below
python3 raccoon_swarm_server.py    # or: gunicorn raccoon_swarm_server:app ...
```

Auth is auto-disabled locally (no `RRI_AUTH_TOKEN`/`RRI_PASSWORD_HASH`), and
`RRI_DEPLOYMENT_PROFILE` defaults to `local`, so nothing extra is required to
run on your own machine.

### Environment

`.env.example` is the inventory. The big ones: model keys
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GROK_API_KEY`/`XAI_API_KEY`,
`PERPLEXITY_API_KEY`), `RRI_STORAGE_DIR` (where the filestore lives),
`RRI_DEPLOYMENT_PROFILE`, auth (`RRI_AUTH_TOKEN` + `RRI_PASSWORD_HASH`), and
SMTP (`SMTP_*` + `RRI_CONDUCTOR_EMAIL`) for the closer. See
[`docs/stack/auth.md`](docs/stack/auth.md) for the security-relevant ones.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest                              # the unit suite
git ls-files '*.py' | xargs python -m py_compile   # syntax guard (CI runs this too)
```

CI (`.github/workflows/tests.yml`) runs both on every PR. Keep new
safety-critical logic **stdlib-only and pure** where possible (see
`swarm_auth.py`, `swarm_deploy.py`) so it's testable on a bare interpreter
without the model stack.

## Adding a tool or route

- **A model-callable tool:** add its schema + dispatch to `swarm_tools.py`
  (`TOOL_DEFINITIONS`). Keep the capability itself in its own `swarm_*.py`
  module; `swarm_tools` is just the registry.
- **An HTTP route:** add it to `raccoon_swarm_server.py` and gate it with
  `@require_auth`. Add a `/<subsystem>/status` endpoint if it's a new
  subsystem — the status surface is how operators see health at a glance.
- Put pure, testable logic in the module and thin glue in the server.

## Architectural notes

- **No vector DB (yet).** Semantic search uses an in-process mtime-cached numpy
  matrix on purpose. The bottleneck was per-query index re-parsing, not the
  cosine math. A real store (Chroma/LanceDB) earns its keep only at ~1e5–1e6
  chunks **or** when multiple reader processes share one index — whichever
  lands first. See the exit-ramp note in `swarm_semantic.py`.
- **Deployment posture is fail-closed + fail-loud.** Don't add a capability
  that's dangerous when public without gating it in `swarm_deploy.py`.

## Branch & PR conventions

- Branch off the default branch; open PRs as **draft** until green.
- Every PR must pass `pytest` + `py_compile` in CI.
- Prefer small, focused PRs with tests over large ones.
