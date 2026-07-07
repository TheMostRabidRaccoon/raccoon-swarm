#!/usr/bin/env python3
"""Publish the Daily Burrow — the Conductor's morning newspaper.

Assembles the last 24h of swarm activity from closer receipts (scorecards,
corpus events, digests), Joy runs, and the email send log, then emails one
mechanical digest — surfacing any closer-reported email gaps verbatim so
owed-but-unsent handoffs stop hiding in subject lines. Also sweeps for PLAY
sessions whose gazette the closer hook missed (crash, disabled, pre-deploy)
and publishes those editions as a backstop.

Why a oneshot script (not a server thread): same isolation rationale as
run_joy.py — plus the paper should still print when the server is down;
"server down" is front-page news, not a reason to skip the edition.

Usage:
  run_daily_burrow.py                 # publish for the last 24h, email it
  run_daily_burrow.py --window-hours 48
  run_daily_burrow.py --dry-run       # print the edition, send nothing
  run_daily_burrow.py --no-email      # persist edition + DOCX, skip SMTP

The swarm-burrow.timer unit invokes the no-arg form once a day.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
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
          "relying on ambient env vars.", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("burrow-runner")


def _resolve_dirs() -> tuple[Path, Path]:
    """LOGS_DIR / OUTPUTS_DIR exactly as the server resolves them, without
    importing the server (the paper must print even if the server can't boot)."""
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RRI_STORAGE_DIR"):
        storage = Path(os.getenv("RRI_STORAGE_DIR", "/data"))
        return storage / "logs", storage / "outputs"
    gdrive = Path.home() / "Library/CloudStorage/GoogleDrive-kad@rabidraccoonintelligence.org/My Drive"
    return gdrive / "Logs_v2_live", gdrive / "Logs_v2_live"


# Attach the DOCX edition only when there's a newspaper's worth of news.
def _should_attach(sessions: list[dict], joy_runs: list[str]) -> bool:
    blockers = sum(s["blockers"] for s in sessions if isinstance(s.get("blockers"), int))
    return (any(s.get("is_play") for s in sessions)
            or bool(joy_runs)
            or blockers >= 1
            or len(sessions) >= 3)


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish the Daily Burrow.")
    parser.add_argument("--window-hours", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the edition; persist nothing, send nothing")
    parser.add_argument("--no-email", action="store_true",
                        help="persist edition + DOCX but skip SMTP")
    args = parser.parse_args()

    import swarm_filestore
    import swarm_gazette
    import swarm_mail

    logs_dir, outputs_dir = _resolve_dirs()
    now = datetime.now()
    since = now - timedelta(hours=args.window_hours)
    date_str = now.date().isoformat()

    sessions = swarm_gazette.collect_sessions(logs_dir, since, now)
    joy_runs = swarm_gazette.collect_joy_runs(since, now)
    email_entries = swarm_gazette.collect_email_log(since, now)
    subject, body = swarm_gazette.build_daily_burrow(
        date_str=date_str, sessions=sessions, joy_runs=joy_runs,
        email_entries=email_entries)

    if args.dry_run:
        print(f"SUBJECT: {subject}\n\n{body}")
        return 0

    edition_path = f"{swarm_gazette.DAILY_LANE}/{date_str}-daily-burrow.md"
    if not swarm_filestore.write_file(edition_path, body):
        logger.error(f"could not persist edition to {edition_path}")
        return 1
    logger.info(f"edition persisted: {edition_path}")

    attachments = None
    if _should_attach(sessions, joy_runs):
        docx_path = outputs_dir / f"daily_burrow_{date_str}.docx"
        if swarm_gazette.render_docx(f"The RRI Daily Burrow — {date_str}", body, docx_path):
            attachments = [str(docx_path)]
            logger.info(f"DOCX edition: {docx_path}")

    # Backstop sweep: publish any PLAY session's gazette the closer hook
    # missed. fire_play_gazette is idempotent via the persisted edition.
    for s in sessions:
        if s.get("is_play"):
            gz = swarm_gazette.fire_play_gazette(
                session_id=s["session_id"], logs_dir=logs_dir, outputs_dir=outputs_dir)
            if gz["published"]:
                logger.info(f"swept play gazette for {s['session_id']} "
                            f"(emailed={gz['emailed']})")

    if args.no_email:
        logger.info("--no-email: skipping SMTP")
        return 0

    sent, reason = swarm_mail.send_operational(
        subject, body, attachments=attachments,
        prefix="[RRI Daily Burrow]", session_id=f"burrow-{date_str}")
    if not sent:
        logger.warning(f"edition persisted but email not sent: {reason}")
        return 0  # the paper printed; delivery failure is logged, not fatal
    logger.info("Daily Burrow delivered.")
    print(json.dumps({"date": date_str, "sessions": len(sessions),
                      "joy_runs": len(joy_runs), "emailed": sent,
                      "attached": bool(attachments)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
