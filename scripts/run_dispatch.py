#!/usr/bin/env python3
"""Process queued dispatch payloads.

Triggered by the swarm-dispatch.path systemd unit when a new file lands
in <storage_root>/swarm/dispatch/queued/. Walks the queued/ dir, calls
the deterministic scripted-episode pipeline for each payload, and writes
a result manifest into done/ or failed/.

Usage:
  run_dispatch.py                 # process every currently queued item
  run_dispatch.py <dispatch_id>   # process one specific item by id
  run_dispatch.py --requeue       # move stuck processing/ items back to queued/

The systemd unit invokes the no-arg form. Manual one-shot runs are useful
for debugging a specific failure.
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env from the repo root so the runner has ELEVENLABS_API_KEY,
# SMTP_*, etc. when invoked from a shell. systemd's EnvironmentFile=
# already covers the unit-triggered case; this covers manual runs.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

import swarm_dispatch  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("dispatch-runner")


def _notify(payload: dict, dispatch_id: str, status_label: str, manifest: dict) -> None:
    """Email the Conductor with the outcome. Best-effort: a notify failure
    must not block the state transition."""
    try:
        import swarm_mail
    except ImportError:
        logger.warning("swarm_mail unavailable — skipping notification")
        return

    title = payload.get("script", {}).get("title") or "Episode"
    prefix = (payload.get("callback_email_subject_prefix") or "").strip()
    subject = f"{prefix} {title} — {status_label}".strip()

    lines = [
        f"Dispatch ID: {dispatch_id}",
        f"Status: {status_label}",
        f"Submitted by: {payload.get('submitted_by')}",
        f"Submitted at: {payload.get('submitted_at')}",
        f"Duration: {manifest.get('duration_s', '?')}s",
        "",
    ]
    if status_label == "DONE":
        video = manifest.get("pipeline", {}).get("stages", {}).get("video", {}) or {}
        if video.get("filename"):
            lines.append(f"Video: {video['filename']}")
            lines.append(f"Download: /download/{video['filename']}")
        if manifest.get("pipeline", {}).get("panel_report"):
            lines.append(f"Panels rendered: {len(manifest['pipeline']['panel_report'])}")
    else:
        if manifest.get("error"):
            lines.append(f"Error: {manifest['error']}")
        for e in (manifest.get("pipeline", {}).get("errors") or []):
            lines.append(f"  - {e}")

    body = "\n".join(lines)
    try:
        ok, reason = swarm_mail.send_to_conductor(
            subject=subject,
            body=body,
            model="dispatch-runner",
            session_id=f"dispatch-{dispatch_id}",
        )
        if not ok:
            logger.warning(f"notify {dispatch_id}: send failed — {reason}")
    except Exception as e:
        logger.warning(f"notify {dispatch_id}: raised {type(e).__name__}: {e}")


def _run_pipeline(payload: dict) -> dict:
    """Lazy-import the server's pipeline so this script's startup stays light
    (the server module pulls in many heavy deps). Returns the pipeline result
    dict — callers inspect 'errors' to determine success."""
    from raccoon_swarm_server import run_scripted_episode_pipeline

    script = payload["script"]
    return run_scripted_episode_pipeline(
        script,
        project_slug=script.get("project_slug"),
    )


def process_one(dispatch_id: str) -> bool:
    """Process a single queued payload. Returns True on success."""
    payload = swarm_dispatch.read_payload(swarm_dispatch.QUEUED, dispatch_id)
    if payload is None:
        logger.warning(f"{dispatch_id}: not in queued/ (already claimed?), skipping")
        return False

    moved = swarm_dispatch.transition(
        dispatch_id, swarm_dispatch.QUEUED, swarm_dispatch.PROCESSING
    )
    if moved is None:
        logger.warning(f"{dispatch_id}: lost the race to processing/, skipping")
        return False

    started = datetime.now()
    manifest: dict = {
        "dispatch_id": dispatch_id,
        "started_at": started.isoformat(timespec="seconds"),
        "submitted_by": payload.get("submitted_by"),
        "submitted_at": payload.get("submitted_at"),
    }

    try:
        result = _run_pipeline(payload)
        manifest["pipeline"] = result
        manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["duration_s"] = round((datetime.now() - started).total_seconds(), 1)

        if result.get("errors"):
            swarm_dispatch.transition(
                dispatch_id, swarm_dispatch.PROCESSING, swarm_dispatch.FAILED
            )
            swarm_dispatch.write_result_manifest(
                dispatch_id, swarm_dispatch.FAILED, manifest
            )
            _notify(payload, dispatch_id, "FAILED", manifest)
            return False

        swarm_dispatch.transition(
            dispatch_id, swarm_dispatch.PROCESSING, swarm_dispatch.DONE
        )
        swarm_dispatch.write_result_manifest(
            dispatch_id, swarm_dispatch.DONE, manifest
        )
        _notify(payload, dispatch_id, "DONE", manifest)
        return True

    except Exception as e:
        logger.exception(f"{dispatch_id}: pipeline raised")
        manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
        manifest["duration_s"] = round((datetime.now() - started).total_seconds(), 1)
        manifest["error"] = f"{type(e).__name__}: {e}"
        manifest["traceback"] = traceback.format_exc()
        swarm_dispatch.transition(
            dispatch_id, swarm_dispatch.PROCESSING, swarm_dispatch.FAILED
        )
        swarm_dispatch.write_result_manifest(
            dispatch_id, swarm_dispatch.FAILED, manifest
        )
        _notify(payload, dispatch_id, "FAILED", manifest)
        return False


def process_queued() -> int:
    queued = swarm_dispatch.list_state(swarm_dispatch.QUEUED, limit=10_000)
    if not queued:
        logger.info("no queued dispatches")
        return 0
    completed = 0
    for item in queued:
        if process_one(item["dispatch_id"]):
            completed += 1
    return completed


def requeue_processing() -> int:
    """Move stuck processing/ items back to queued/. Use after a runner crash."""
    stuck = swarm_dispatch.list_state(swarm_dispatch.PROCESSING, limit=10_000)
    moved = 0
    for item in stuck:
        if swarm_dispatch.transition(
            item["dispatch_id"], swarm_dispatch.PROCESSING, swarm_dispatch.QUEUED
        ):
            moved += 1
    logger.info(f"re-queued {moved} stuck dispatches")
    return moved


def main() -> int:
    parser = argparse.ArgumentParser(description="Process queued swarm dispatches.")
    parser.add_argument("dispatch_id", nargs="?", help="Specific dispatch id to process.")
    parser.add_argument("--requeue", action="store_true",
                        help="Move stuck processing/ items back to queued/ and exit.")
    args = parser.parse_args()

    if args.requeue:
        requeue_processing()
        return 0
    if args.dispatch_id:
        return 0 if process_one(args.dispatch_id) else 1
    process_queued()
    return 0


if __name__ == "__main__":
    sys.exit(main())
