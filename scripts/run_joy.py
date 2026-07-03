#!/usr/bin/env python3
"""Run one bounded Joy Mode session — the daily Core-4 play ritual.

Joy Mode is play WITH receipts: one activity, two rounds (parallel then daisy),
one artifact, one reflection, one MECHANICAL scorecard, persisted under the
filestore's joy/ lane. See swarm_joy.py for the design rationale.

Why a separate oneshot process (not an endpoint in the live server):
  The server tracks persona mode as module globals (_sovereignty_mode /
  _play_mode). A Joy run inside the live Flask process could leak mode into a
  concurrent human session. Running here as a systemd oneshot isolates that
  global state — this process exits when the ritual is done.

The heavy lifting (model calls, synthesis) lives in raccoon_swarm_server; this
script just wires the server's engine into swarm_joy.run_joy_session, which is
otherwise import-light and server-free (round runner is injected).

Usage:
  run_joy.py                # run today's ritual
  run_joy.py --date 2026-07-03   # re-run a specific day (deterministic pick)
  run_joy.py --dry-run      # pick + print today's activity, run nothing

The swarm-joy.timer unit invokes the no-arg form once a day.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Auto-reexec under the repo venv if a system Python (missing our deps) invoked
# us. systemd unit invocations already use the venv path directly; this only
# matters for manual shell runs. Mirrors scripts/run_dispatch.py.
_VENV_PY = REPO_ROOT / "venv" / "bin" / "python3"
if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    print(
        f"WARNING: python-dotenv not importable in {sys.executable}.\n"
        f"         .env will not be loaded; expect missing-API-key errors.\n"
        f"         Fix: {_VENV_PY} -m pip install python-dotenv",
        file=sys.stderr,
    )

import swarm_joy  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("joy-runner")


def _core4_models(server):
    """The core-four subset of the server's call functions, keyed to match
    swarm_joy.CORE_4 (lowercase). Perplexity (research seat) sits out playtime.

    Keys MUST match the order swarm_joy passes to the round runner, or
    run_loop_round's `[n for n in order if n in models]` filter drops everyone.
    """
    missing = [m for m in swarm_joy.CORE_4 if m not in server.SWARM_SINGLE]
    if missing:
        raise RuntimeError(f"server.SWARM_SINGLE missing core-4 seats: {missing}")
    return {m: server.SWARM_SINGLE[m] for m in swarm_joy.CORE_4}


def _make_round_runner(server):
    """Adapt swarm_joy's (prompt, models, mode, order) call shape onto the
    server's run_loop_round keyword signature, pinning a stable joy session id
    (for per-session tool rate limiting) and no images."""
    def round_runner(prompt, models, mode, order):
        return server.run_loop_round(
            prompt, models=models, images=None,
            session_id="joy", mode=mode, order=order,
        )
    return round_runner


def _notify(result: dict) -> None:
    """Best-effort Conductor ping so the daily ritual is visible. A notify
    failure must never fail the run."""
    try:
        import swarm_mail
    except ImportError:
        logger.info("swarm_mail unavailable — skipping notification")
        return
    if not result.get("ok"):
        subject = "Joy Mode — run skipped"
        body = f"Joy run did not complete: {result.get('error', 'unknown')}"
    else:
        sc = result.get("scorecard", {})
        subject = f"Joy Mode — {result['activity']} ({result['date']})"
        body = "\n".join([
            f"Activity: {result['activity']}",
            f"Date: {result['date']}",
            f"Rounds: {sc.get('rounds')}  Duration: {sc.get('duration_sec')}s",
            f"Artifact: {'yes' if sc.get('artifact_present') else 'no'}  "
            f"Reflection: {'yes' if sc.get('reflection_present') else 'no'}",
            f"Falsifiable claims logged: {sc.get('falsifiable_claims')}",
            f"New tool proposed: {'yes' if sc.get('new_tool_proposed') else 'no'}",
            "",
            f"Run folder: {result.get('files', {}).get('artifact', '')}",
        ])
    try:
        ok, reason = swarm_mail.send_to_conductor(
            subject=subject, body=body, model="joy-runner",
            session_id=f"joy-{result.get('date', 'unknown')}",
        )
        if not ok:
            logger.info(f"notify: send skipped/failed — {reason}")
    except Exception as e:
        logger.warning(f"notify raised {type(e).__name__}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Joy Mode session.")
    parser.add_argument("--date", help="YYYY-MM-DD to run (default: today). "
                        "The activity pick is deterministic from this date.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Pick and print today's activity, then exit without running.")
    args = parser.parse_args()

    activities = swarm_joy.ensure_activities()
    if not activities:
        logger.error("no accepted activities in joy/activities.md — nothing to run")
        return 1

    if args.dry_run:
        date_str = args.date or None
        import datetime as _dt  # local: only the dry-run path needs a clock
        date_str = date_str or _dt.date.today().isoformat()
        activity = swarm_joy.pick_activity(
            activities, date_str, swarm_joy.recent_run_slugs())
        logger.info(f"[dry-run] {date_str} would run: {activity['slug']} — {activity['title']}")
        return 0

    # Lazy-import the server only for a real run; it pulls heavy deps.
    logger.info("importing swarm server engine...")
    import raccoon_swarm_server as server

    result = swarm_joy.run_joy_session(
        _make_round_runner(server),
        server.run_synthesis,
        core4_models=_core4_models(server),
        date_str=args.date,
    )

    if result.get("ok"):
        logger.info(f"joy run complete: {result['activity']} ({result['date']})")
    else:
        logger.error(f"joy run failed: {result.get('error')}")
    _notify(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
