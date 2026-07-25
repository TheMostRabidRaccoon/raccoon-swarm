#!/usr/bin/env python3
"""Compost sweep — the janitor for ephemeral code runs.

Moves code_exec runs whose manifest says "ephemeral": true and whose age
exceeds N days into artifacts/code-runs/_composted/. Everything else is
never touched: non-ephemeral runs, runs with missing or unreadable
manifests, and runs whose age can't be parsed all stay put — every
ambiguity fails toward keeping.

Origin: the free-play "temperature-deaf archive" note (swarm-lab PR #7).
The archive had permanent memory for deliberate jokes and careful decay
only for positions; this sweep finally reads the temperature signal the
manifests were already carrying.

Why a oneshot script (not a server thread): same rationale as
run_daily_burrow.py — the sweep is calendar work, it should run whether or
not the server is up, and a crash here must never take deliberation down.

Usage:
  run_compost_sweep.py             # sweep runs older than RRI_COMPOST_AFTER_DAYS (default 7)
  run_compost_sweep.py --days 30   # override the age threshold
  run_compost_sweep.py --dry-run   # report what would be composted, move nothing

Wire it to a daily systemd timer or cron entry once you trust the dry-run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Auto-reexec under the repo venv if a system Python invoked us (manual shell
# runs; systemd units use the venv path directly). Mirrors scripts/run_joy.py.
_VENV_PY = REPO_ROOT / "venv" / "bin" / "python3"
if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    print(f"WARNING: python-dotenv not importable in {sys.executable}; "
          "relying on ambient environment variables.", file=sys.stderr)

import swarm_codeexec


def main() -> int:
    parser = argparse.ArgumentParser(description="Compost ephemeral code runs past their keep-by date.")
    parser.add_argument("--days", type=int, default=None,
                        help="Age threshold in days (default: RRI_COMPOST_AFTER_DAYS or 7).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be composted without moving anything.")
    args = parser.parse_args()

    result = swarm_codeexec.compost_sweep(older_than_days=args.days, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
