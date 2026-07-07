# Gazette Layer — Daily Burrow + Play Gazette

**Newspaper-style Conductor emails, assembled ONLY from receipts on disk —
never from model narration.** Two editions: a once-a-day Daily Burrow digest
of the last 24h, and a per-session Play Gazette (with DOCX attachment) fired
when a PLAY-shaped session closes.

## Source of truth

- `swarm_gazette.py` — collectors, editions, DOCX renderer, play publisher
- `swarm_mail.py` — `send_operational()` (attachment invariant lives here)
- `swarm_closer.py` — end-of-`_worker` play-gazette hook
- `scripts/run_daily_burrow.py` — the daily runner (server-free)
- `systemd/swarm-burrow.{service,timer}`

## Data sources (all receipts, no narration)

| Receipt | Feeds |
|---|---|
| `logs/scorecard-<sid>.json` | ledger row: rounds, models, gaps, directives, truncations |
| `logs/corpus/corpus-<sid>.json` | query, repo_sha |
| `logs/closer-digest-<sid>.md` | "What needs you" bullets (carried verbatim) |
| `joy/runs/**` (filestore) | Joy run list |
| `logs/emails.log` (filestore) | email-channel ground truth |

## Honesty invariants

- **Attachment invariant**: `send_operational` verifies + sha256-hashes every
  attachment BEFORE the send and refuses the whole email if any file is
  missing. The emails.log entry records name + hash + status. "I attached the
  newspaper" can never outrun the newspaper.
- **Gap surfacing**: a closer `audit_counts.gap > 0` is repeated verbatim in
  the Burrow ("N owed email(s) did NOT send") with a pointer to the digest's
  "What was flagged" section — undelivered handoffs stop hiding in subject
  lines.
- **Unmeasured ≠ 0**: missing scorecard fields render as `?` in the ledger.
- **Idempotency**: the persisted filestore edition
  (`artifacts/gazettes/play/<date>_<sid>-gazette.md`) is the marker; the
  closer hook and the daily sweep can both fire without double-publishing.
- No DOCX library / no SMTP → the edition still persists; the email (if any)
  goes out honestly unattached; nothing raises.

## PLAY detection (mechanical)

`[SESSION_PURPOSE: creative-production]` wins; else a documented marker list
over the query (`swarm_gazette.PLAY_MARKERS`). Extend by PR, not vibes.

## Channels + caps

`send_operational` is a **system-level channel** (same doctrine as the
closer's digest sends): recipient locked to `RRI_CONDUCTOR_EMAIL`, NOT
reachable from `[EMAIL_CONDUCTOR]` directives, and exempt from the per-model
rate caps — a busy swarm day must not starve the Conductor's own newspaper.

## Ops

- Enable the morning edition: `systemctl enable --now swarm-burrow.timer`
  (08:30 daily, `Persistent=true`).
- Manual print: `scripts/run_daily_burrow.py --dry-run` (stdout only),
  `--no-email` (persist + DOCX, no SMTP), `--window-hours 48`.
- Kill switch: `RRI_GAZETTE_ENABLED=false` disables the closer's play hook
  (the daily timer is controlled by systemd, not this flag).
- Editions land in `artifacts/gazettes/{daily,play}/` (filestore) + DOCX in
  `OUTPUTS_DIR` (served via `/download/`).
