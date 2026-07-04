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

## Merged ≠ deployed — restart after every merge

The swarm is **governed by `main` but operated by the loaded process.** A fix
merged to `main` is not live until the service restarts — until then the running
server executes pre-merge code, and a seat's "verified against main" says
nothing about the runtime it actually lives in. Session 133 hit this: a
nested-directory fix that was on `main` still failed in the running server.

- **Ritual:** restart the swarm service after every merge that touches server
  code (`sudo systemctl restart swarm.service`, or your process manager).
- **Detector:** `GET /version` reports `boot_commit` (what the running process
  loaded) vs `head_commit` (what's checked out now). `up_to_date: false` means
  the working tree advanced past the process — **restart to deploy.** Pin claims
  about deployed behaviour to `boot_commit`, not to `main`. Unauthenticated (a
  commit SHA, no secrets) so any seat or health check can hit it.

## Monitoring

- **Status endpoints** — `/websearch/status`, `/prosody/status`,
  `/semantic/status`, `/dispatch/status`, `/mail/status`. Glanceable
  per-subsystem health.
- **Scorecards** — every session close writes `logs/scorecard-<id>.json`
  (mechanical counters). Watch `persistence_gap`: it's the count of distinct
  paths a model *claimed* to write that don't exist on disk. `null` +
  `phantom_write_claims_status: "unavailable"` means the detector couldn't run
  (unknown ≠ zero). `filestore.honest_verb_violations` is the strict subset of
  that gap asserted with **strong completion language** ("written and verified,
  read back, byte matches") — active deception, not an incidental mention.
  Existence is the gate; the completion cues only *sort severity* — this is a
  count, never a self-graded verdict. It's the fail-LOUD **measurement** of the
  read-back invariant; turning it into a fail-CLOSED consequence (voiding a
  turn) is deferred until this count shows the real false-positive rate.
- **Closer digests** — `logs/closer-digest-<id>.md`, emailed to the Conductor.
- **Corpus events** — every session close also writes `logs/corpus/corpus-<id>.json`
  (`swarm_corpus`): a structured, **SHA-anchored** record of the session —
  participation, governance signals (directives + phantom / honest-verb
  violations, read from the scorecard), and mechanical **interaction proxies**
  (disagreement / convergence keyword counts, explicitly labelled a heuristic,
  never ground-truth dissent). Research-data collection as a byproduct of
  running; the `repo_sha` field pins each record to a commit you can check out
  and re-verify (a claim "verified against live main" is worthless once main
  moves). Fail-loud like the scorecard — a write failure never aborts a session.

### Doctrine: the synthesis is the product; the scorecard is the instrument

Scorecard emission is **mandatory-attempt, fail-loud — not session-gating.**
The closer runs post-session on a daemon thread; a scorecard write failure is
logged loudly but must **never** discard or invalidate completed synthesis
work. Making the product invalid because an *observer* failed to write
telemetry would invert the system's authority hierarchy — the same class of
mistake as letting self-graded usefulness scores become the product.

## Read-back verification (runner-enforced, both directions)

Between rounds the runner re-reads the filestore on disk and injects ground
truth into the next round — the model is never trusted to self-verify:

- **Phantom writes** (`verify_round_claims`): a model narrates a save it never
  actually persisted → the claimed-but-absent path is surfaced as a phantom.
- **False ghosts** (`verify_ghost_claims`): a model declares a live file
  missing/void ("not found", "a ghost") → the runner re-reads it; if it exists,
  a `READ-BACK CORRECTION` is injected. This closes the failure a real Joy Mode
  session hit — the seats convicted a live 1674-byte file as a ghost off one
  narrated negative read-back, in the same round they canonized the rule against
  it. A narrated negative read-back is not a read-back; the disk is the arbiter.

Both emit SSE events (`filestore_phantom_writes`, `filestore_false_ghosts`).

### Write-audit log — lag vs. loss, made observable

`logs/write-audit.jsonl` records every filestore write attempt: `{ts, model,
path, channel, result}`. `channel` is the load-bearing field:

- `tool` — a synchronous `filestore_write`/`_append` tool call; settles mid-turn.
- `directive` — a `[MEMORY_WRITE]` block; settles at the **round boundary**
  (`process_round_writes`), *after* the emitting seat's turn.

That async gap is the mechanism behind Session-133's "phantom" writes: a
directive write isn't on disk when the *next* seat looks, so it reads as missing
— lag, not loss. `result: rejected` rows capture the other cause (a blocked
path/extension the emitting seat wasn't told about). The log makes both
observable instead of inferred, and tags `write_channel` so seat-level phantom
rates are actually comparable (they are not, untagged — a Paper 2 confound).
Best-effort telemetry: an audit-log failure never blocks the underlying write.

## Joy Mode (daily play ritual)

A bounded daily Core-4 ritual, run as a **systemd oneshot** (isolates the
server's persona-mode globals). Fired by `swarm-joy.timer`; runs land under
`swarm/joy/runs/<date>/` with a mechanical scorecard. Its `tiny-tool-invention`
activity queues tool proposals that `swarm-proposals.path` files as GitHub
issues — the swarm designs/tests/files autonomously, **merging into the live
registry stays a human PR** (the one gated step). Full first-run + enable +
token setup runbook: [`stack/joy.md`](stack/joy.md).

## Recovery

- **Dispatch stuck in `processing/`** (runner crashed mid-pipeline):
  `./scripts/run_dispatch.py --requeue` (see [`../systemd/README.md`](../systemd/README.md)).
- **Joy proposal stuck in `queued/`/`failed/`:** inspect it, fix the cause, then
  `./scripts/file_proposals.py <proposal_id>` (see [`stack/joy.md`](stack/joy.md)).
- **Semantic index stale/empty:** `POST /semantic/reindex` or
  `scripts/build_semantic_index.py`.
- **Single worker is deliberate** — the daemon, in-memory session state, and
  SSE registries are not multi-worker safe. Keep `--workers=1`.
