# Operations

**How is this deployed, monitored, recovered, and kept safe?**

## Canonical deployment

> **Canonical = the path that can resurrect the *full* production stack from
> the docs — not merely the path that boots the Flask app.**

By that acceptance test — *"can a future operator rebuild dispatch, the `.path`
watcher, the ffmpeg/video pipeline, the persistent filestore, prosody
adjacency, and `code_exec` profile behavior from these docs?"* — the blessed
path is:

**A single Linux VM managed by systemd.**

It is blessed because it supports the complete operational surface:

- Gunicorn/Flask swarm server (`Procfile` command works here too)
- persistent filestore on a mounted volume (`RRI_STORAGE_DIR`)
- systemd-managed service lifecycle
- the dispatch queue watcher (`systemd/swarm-dispatch.path` + `.service`)
- the scripted-episode runner + ffmpeg/video composition
- closer digests + scorecards under `logs/`
- deployment-profile safety checks (`swarm_deploy.py`)
- local/LAN prosody integration

Install steps for the dispatch units live in [`../systemd/README.md`](../systemd/README.md).
Hosting/runtime specifics are in [`stack/deploy.md`](stack/deploy.md).

## Experimental deployment

**Railway / Procfile is experimental and supports the web-server subset only.**
It is fine for the hosted UI and quick sessions, but it is **not** the blessed
recovery path for the full stack: the heavy pipeline features (dispatch,
watcher, media composition, persistent-volume + recovery semantics) are
secondary or stubbed there. Do not rely on it for full-stack recovery unless
and until those are explicitly supported and documented.

## Deployment profiles (safety posture)

`RRI_DEPLOYMENT_PROFILE = local | lan | public` — enforced at boot, **fail
closed + fail loud**. Full table and rationale in [`stack/auth.md`](stack/auth.md).

- `local` (default) — homelab; current behavior, nothing to configure.
- `lan` — trusted network; persistent secret expected, `code_exec` warned.
- `public` — internet-facing; LAN bypass **off**, auth **required**, and the
  server **refuses to boot** unless `code_exec` declares a real sandbox
  (`RRI_CODEEXEC_SANDBOX=...`) or the risk is explicitly accepted
  (`RRI_ALLOW_UNSAFE_PUBLIC_CODEEXEC=true`). Re-enabling the CIDR bypass on
  public requires the explicit `RRI_ALLOW_PUBLIC_TRUSTED_CIDRS=true`.

## Monitoring

- **Status endpoints** — `/websearch/status`, `/prosody/status`,
  `/semantic/status`, `/dispatch/status`, `/mail/status`. Glanceable
  per-subsystem health.
- **Scorecards** — every session close writes `logs/scorecard-<id>.json`
  (mechanical counters). Watch `persistence_gap`: it's the count of distinct
  paths a model *claimed* to write that don't exist on disk. `null` +
  `phantom_write_claims_status: "unavailable"` means the detector couldn't run
  (unknown ≠ zero).
- **Closer digests** — `logs/closer-digest-<id>.md`, emailed to the Conductor.

### Doctrine: the synthesis is the product; the scorecard is the instrument

Scorecard emission is **mandatory-attempt, fail-loud — not session-gating.**
The closer runs post-session on a daemon thread; a scorecard write failure is
logged loudly but must **never** discard or invalidate completed synthesis
work. Making the product invalid because an *observer* failed to write
telemetry would invert the system's authority hierarchy — the same class of
mistake as letting self-graded usefulness scores become the product.

## Recovery

- **Dispatch stuck in `processing/`** (runner crashed mid-pipeline):
  `./scripts/run_dispatch.py --requeue` (see [`../systemd/README.md`](../systemd/README.md)).
- **Semantic index stale/empty:** `POST /semantic/reindex` or
  `scripts/build_semantic_index.py`.
- **Single worker is deliberate** — the daemon, in-memory session state, and
  SSE registries are not multi-worker safe. Keep `--workers=1`.
