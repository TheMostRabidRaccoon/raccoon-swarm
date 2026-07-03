# Systemd units

Units that wire background swarm rituals into systemd.

## Dispatch queue

Two units wire the dispatch queue so a payload landing in
`swarm/dispatch/queued/` triggers `scripts/run_dispatch.py` instantly.

- `swarm-dispatch.path` — watcher. Activates on file changes under
  `swarm/dispatch/queued/`.
- `swarm-dispatch.service` — oneshot runner. Invoked by the path unit;
  exits cleanly so the next file change triggers a fresh run.

## Joy Mode (daily play ritual)

Two units run the bounded Core-4 play ritual once a day (see
`swarm_joy.py` for the design; `scripts/run_joy.py` is the entrypoint).

- `swarm-joy.service` — oneshot runner. Runs one ritual as a **separate
  process** so the server's persona-mode module globals can't leak into a
  concurrent human session, then exits.
- `swarm-joy.timer` — fires the service daily (`OnCalendar=11:00`,
  `Persistent=true`, 10-min jitter). The activity pick is deterministic
  from the date, so the exact minute is irrelevant.

Install + test:

```bash
sudo cp systemd/swarm-joy.service systemd/swarm-joy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now swarm-joy.timer
systemctl list-timers swarm-joy.timer          # confirm next fire time

# Dry-run today's pick without spending any tokens:
./scripts/run_joy.py --dry-run
# Force a full run now (or re-run a past day — deterministic pick):
sudo systemctl start swarm-joy.service         # today
./scripts/run_joy.py --date 2026-07-03         # a specific day
sudo journalctl -u swarm-joy.service -f
```

Runs land under `swarm/joy/runs/<date>/` (prompt, transcript, artifact,
reflection, scorecard). The scorecard is mechanical-only by design — no
self-graded "joy score."

## Install

Both units assume the swarm runs as user `theconductor` from
`/home/theconductor/raccoon-swarm/` with a venv at
`/home/theconductor/raccoon-swarm/venv/`. Adjust paths inline if your
layout differs.

```bash
sudo cp systemd/swarm-dispatch.path systemd/swarm-dispatch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now swarm-dispatch.path
sudo systemctl status swarm-dispatch.path
```

## Verify

```bash
# 1. Confirm the watcher is active
sudo systemctl status swarm-dispatch.path

# 2. Drop a test payload (replace <id>.json content with a real script)
cp scripts/pigeons_ep2.json swarm/dispatch/queued/test_$(date +%s).json
# or use the Python API:
#   python3 -c "import swarm_dispatch, json;
#               print(swarm_dispatch.write_payload(
#                   {'dispatch_version':'1','submitted_by':'manual',
#                    'submitted_at':'2026-05-09T00:00:00',
#                    'script': json.load(open('scripts/pigeons_ep2.json'))}))"

# 3. Watch the runner pick it up
sudo journalctl -u swarm-dispatch.service -f
```

## Recovery

If the runner crashes mid-pipeline, the payload is stuck in
`processing/`. Re-queue it:

```bash
cd /home/theconductor/raccoon-swarm
./scripts/run_dispatch.py --requeue
```

Or invoke the runner against a specific id manually:

```bash
./scripts/run_dispatch.py 20260509T143200_s01e02_swarm-session-62
```
