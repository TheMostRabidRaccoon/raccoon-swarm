# Systemd units

Two units that wire the dispatch queue into systemd so a payload landing
in `swarm/dispatch/queued/` triggers `scripts/run_dispatch.py` instantly.

## Files

- `swarm-dispatch.path` — watcher. Activates on file changes under
  `swarm/dispatch/queued/`.
- `swarm-dispatch.service` — oneshot runner. Invoked by the path unit;
  exits cleanly so the next file change triggers a fresh run.

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
