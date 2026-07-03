# Architecture

**What are the pieces, and how does data move?**

The system is a **hub + satellites** design: one Flask server orchestrates
deliberation and synthesis; every capability lives in its own `swarm_*.py`
module with a single responsibility. That grain is deliberate — a model or
human can work on one subsystem without loading the whole stack into context.

## Modules

| Module | Responsibility |
|--------|----------------|
| `raccoon_swarm_server.py` | The hub. Flask routes, deliberation loops (loop / round-table / attention-lab / woodland-council), synthesis, UI, auth, the swarm daemon, SSE streams. |
| `swarm_tools.py` | Unified tool registry — the tool schemas + dispatch the models call (`filestore_*`, `code_exec`, `web_search`, `web_verify`, `image_generate`, `mail`, `dispatch_queue_write`). |
| `swarm_filestore.py` | Persistent shared memory (`positions/`, `questions/`, `pursuits/`, `tasks/`, `frameworks/`, `artifacts/`, `logs/`, `joy/`). Path safety, atomic writes, and **write verification** (phantom-claim detection). The `joy/` lane is kept out of the normal worker's auto-injected context (still indexable/searchable). |
| `swarm_semantic.py` | Semantic search over the filestore — OpenAI embeddings, an mtime-keyed in-process cache, metadata filters + hybrid keyword/vector. No vector DB (see OPERATIONS). |
| `swarm_auth.py` | Stdlib-only auth primitives: constant-time token/password comparison, trusted-CIDR parsing. |
| `swarm_deploy.py` | Stdlib-only deployment profiles (`local`/`lan`/`public`) — fail closed, fail loud. |
| `swarm_dispatch.py` | Production-pipeline dispatch **queue** — a filesystem state machine (`queued/ → processing/ → done|failed/`) with atomic transitions. |
| `swarm_codeexec.py` | Sandboxed Python runner (homelab-grade; gated on `public` by the deployment profile). |
| `swarm_imagegen.py` | Image generation — Gemini Imagen / Grok Imagine / OpenAI backends. |
| `swarm_websearch.py` / `swarm_webverify.py` | Web search (Tavily default) and URL-existence verification. |
| `swarm_prosody.py` | Emotion-map / reverse-TTS via the `prosody-intelligence` engine. |
| `swarm_mail.py` | The swarm's one outbound channel: email the Conductor. |
| `swarm_orchestrator.py` | Round Orchestrator — winds down runaway tool loops, detects truncations. |
| `swarm_closer.py` | Post-session Closer — emails a digest **and** writes the mechanical `scorecard-<id>.json` (incl. `persistence_gap`). |
| `swarm_joy.py` | **Joy Mode** — a bounded daily Core-4 play ritual with receipts (one activity → artifact → reflection → **mechanical** scorecard, persisted under `joy/`). Server-free (round runner injected); own personal-data-free context; invented tools are *proposed*, never auto-installed. |
| `raccoon_mcp_server.py` | Exposes the filestore + code_exec / image_generate / web_search as MCP tools for external clients. |
| `scripts/run_dispatch.py` | The dispatch **runner** — executes the video pipeline for queued payloads. |
| `scripts/run_joy.py` | The Joy Mode **runner** — wires the server engine into `swarm_joy` and runs one ritual as a systemd oneshot (isolates persona-mode globals). Fired daily by `swarm-joy.timer`. |
| `scripts/swarm_observer.py` | Cross-session observer (reads across sessions; never writes to the swarm filestore). |

## Request → response data flow

```
HTTP request
  → auth            (require_auth + deployment profile: local/lan/public)
  → route           (a deliberation mode in raccoon_swarm_server.py)
  → rounds          (the 5 models respond; later speakers may see earlier ones)
      └ tool_use    (swarm_tools → filestore / semantic / code_exec /
                     web_search / web_verify / image_generate / mail / dispatch)
  → orchestrator    (winds down tool loops before the cliff)
  → synthesis       (dual-model synthesis merges the round)
  → persist         (MEMORY_WRITE directives land in the filestore)
  → closer          (digest email + scorecard: counters + persistence_gap)
```

## Production pipeline (async, off the request path)

```
synthesis (image-review passed)
  → swarm_dispatch.write_payload()      → swarm/dispatch/queued/<id>.json
  → systemd swarm-dispatch.path watcher → scripts/run_dispatch.py
  → TTS + frames + ffmpeg composition   → done/ (+ manifest) | failed/
  → email the Conductor
```

The boundary is deliberate: **model-driven phases upstream, deterministic
Python downstream.** Creative raccoons write the script; the machine renders
the video.

## Governance loop

`route → deliberate → verify → persist → score → observe → adapt`

- **verify / persist** — `swarm_filestore` write-verification: announcing a
  write is not a write (the Existence Criterion).
- **score** — `swarm_closer` scorecard: mechanical counters + `persistence_gap`
  computed from *verified* filestore paths.
- **observe** — `scripts/swarm_observer.py`, read-only across sessions.
