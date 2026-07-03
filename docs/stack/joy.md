# Joy Mode

**A bounded daily play ritual for the core four (Claude, GPT, Grok, Gemini) —
play *with receipts*.** One activity → two rounds → one artifact → one
reflection → one **mechanical** scorecard, persisted under the filestore's
`joy/` lane. It runs itself daily; no human in the loop for the play.

## Source of truth

- `swarm_joy.py` — the ritual (server-free; round runner injected)
- `swarm_proposals.py` — the tool-proposal queue (the autonomy handoff)
- `scripts/run_joy.py` — the daily runner
- `scripts/file_proposals.py` — the proposal filer
- `systemd/swarm-joy.{service,timer}`, `systemd/swarm-proposals.{path,service}`

## What a run does

1. **Pick** — one activity, chosen *deterministically from the date* (auditable,
   reproducible) with a cooldown so activities rotate, then a **fuel check**:
   if the day's first pick has no substance to work on (e.g. swarm-kata with an
   empty failure backlog), it's skipped — logged in the scorecard's
   `activities_skipped_no_fuel` — and the next activity in the rotation runs.
   Only entries under `## Accepted` in `joy/activities.md` are eligible;
   `## Proposed` is quarantined until the council promotes them. (Fuel makes the
   pick depend on filestore state, so re-running an old date can differ if the
   fuel changed — a deliberate trade of strict reproducibility for not
   performing empty reps.)
2. **Play** — two rounds across the core four: round 1 parallel (ideate), round
   2 daisy (converge + build), then a dual-grader synthesis.
3. **Persist** — everything lands under `swarm/joy/runs/<date>/`:
   `prompt.md`, `transcript.json`, `artifact.md`, `reflection.md`,
   `scorecard.json` (+ `tool-proposal.md` on a tiny-tool day).

The context Joy builds is **its own** — the activity brief plus recent joy
reflections. It deliberately does **not** pull the normal worker's
recent-files / Drive context, so no Gmail/Drive/personal files leak into
playtime. Symmetrically, the `joy/` lane is kept out of the worker's
auto-injected context, so play doesn't bleed into work (still searchable).

### Why a separate process

`run_joy.py` runs the ritual as a **systemd oneshot**, not an endpoint in the
live server. The server tracks persona mode as module globals
(`_sovereignty_mode` / `_play_mode`); a Joy run inside the live Flask process
could leak mode into a concurrent human session. A separate process isolates
that global state, then exits.

## The scorecard is mechanical — by design

`joy/runs/<date>/scorecard.json` carries only countable fields and ground-truth
results — never a self-graded "joy score" (that's vibes with indentation, the
same trap the session closer avoids). Fields:

- `artifact_present` / `reflection_present` — booleans (did the block exist)
- `code_exec_verified` — `true`/`false` only when the activity had a code_exec
  ground-truth check; **`null`** when it isn't verification-shaped (null ≠ "we
  checked and it failed")
- `falsifiable_claims` — count of confidence-percentage predictions logged
  (Calibration Casino fuel)
- `new_tool_proposed` — `true` only when a proposal was actually parsed **and**
  queued, not merely because it was a tiny-tool day
- `reflection_floor_applied` — `true` when the session omitted the required
  reflection and a stub was written in its place (a floored run is a logged
  fact; `reflection_present` stays `false`, honestly)
- `activities_skipped_no_fuel` — the activities the fuel check passed over before
  landing on this one, with reasons

Note: there is deliberately **no** self-graded "definition of done met" field.
A model declaring its own work complete is self-assessment — the exact thing the
mechanical scorecard exists to avoid. Completion is inferred from countable
facts (`artifact_present`, `code_exec_verified`), never self-report.

## First run (do this before enabling the timer)

On the VM, from the repo root:

```bash
# 1. See what today (or any day) would pick — spends NO tokens.
./scripts/run_joy.py --dry-run
./scripts/run_joy.py --dry-run --date 2026-07-10

# 2. Do one real run now and watch it. Seeds joy/activities.md on first call.
./scripts/run_joy.py
#    (or, once the unit is installed: sudo systemctl start swarm-joy.service
#     && sudo journalctl -u swarm-joy.service -f)

# 3. Confirm the five files landed and the scorecard is sane.
ls swarm/joy/runs/$(date +%F)/
cat swarm/joy/runs/$(date +%F)/scorecard.json
```

If a seat errors, the run still completes (the synthesis handles an absent
model); check the transcript. A wrong model id 404s at call time — roll it back
via the `RRI_*_MODEL` env (see [`models.md`](models.md)).

## Enable the daily ritual

```bash
sudo cp systemd/swarm-joy.service systemd/swarm-joy.timer /etc/systemd/system/
sudo cp systemd/swarm-proposals.path systemd/swarm-proposals.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now swarm-joy.timer swarm-proposals.path
systemctl list-timers swarm-joy.timer          # confirm next fire time
```

The timer fires daily (`OnCalendar=11:00`, `Persistent=true`, 10-min jitter).
The exact minute is irrelevant — the pick is deterministic from the date.
Units assume user `theconductor` at `/home/theconductor/raccoon-swarm` with a
venv; edit the paths inline if your layout differs. Full install/verify notes
in [`../../systemd/README.md`](../../systemd/README.md).

## The autonomy handoff (tool proposals)

The one activity that reaches outside the sandbox is **Tiny Tool Invention**.
On that day the swarm designs a tool and emits a `[TOOL_PROPOSAL]` block; the
run parses it, queues it under `swarm/joy/proposals/queued/`, and the filer
(fired by `swarm-proposals.path`) opens a **GitHub issue** for review.

> **The autonomy split.** The swarm may **design, test, document, and file** a
> proposal on its own — an issue is free and changes nothing that runs.
> **Merging the tool into the live registry stays a human-reviewed PR** — the
> one gated step. Running self-authored code in the live server is the
> break-the-system risk, and only that step is gated. The raccoon may discover
> fire; it does not get unsupervised matches.

Every filed issue leads with that gate banner + a pre-promotion checklist
(schema injection / path-safety review, honest risk notes, test fleshed out,
wired behind the deployment-profile gate).

### Turning on GitHub filing (optional)

Without a token the filer **emails the Conductor** the ready-to-paste issue
(needs `SMTP_*` + `RRI_CONDUCTOR_EMAIL`). To let it open issues directly, set in
`.env` a **fine-grained** token scoped to **Issues: write on this one repo**:

```bash
RRI_GITHUB_PROPOSAL_TOKEN=github_pat_...
RRI_GITHUB_PROPOSAL_REPO=TheMostRabidRaccoon/raccoon-swarm
# RRI_GITHUB_PROPOSAL_LABELS=tool-proposal,needs-review   # optional; must pre-exist
```

Keep the token minimal on purpose: issues-write only, single repo. It never
needs contents/PR scope — promotion is a human PR, not the swarm's job.

## Monitoring & recovery

- **Runs** — `swarm/joy/runs/<date>/`. The reflections stream also appends to
  `joy/ideas/reflections-log.md` (Calibration Casino fuel).
- **Proposal queue** — `swarm/joy/proposals/{queued,filed,failed}/`. State moves
  `queued → filed` on success, or `queued → failed` **only** on a GitHub 4xx
  rejection. Transport errors leave the proposal in `queued/` so the next
  trigger retries — nothing is lost.
- **Re-file a stuck/failed proposal** — inspect it, fix the cause, then:
  `./scripts/file_proposals.py <proposal_id>` (or `--dry-run` to preview the
  backend + title without transitioning anything).
- **Re-run a specific day** — a day that already has a scorecard is a no-op
  (the date-lock that makes timer retries idempotent). To force a fresh run,
  add `--force`: `./scripts/run_joy.py --date YYYY-MM-DD --force`.

## Extending the activity registry

`joy/activities.md` is swarm-editable memory, seeded on first run. Add
candidates under `## Proposed`; promote to `## Accepted` (the only eligible
section) after review. Each entry is `### slug — Title` + a prompt body. The
seed set is ranked from the Core-4 council vote — Swarm Kata, Calibration
Casino (the one that compounds), Puzzle Relay, Constraint Art, Tiny Tool
Invention.
