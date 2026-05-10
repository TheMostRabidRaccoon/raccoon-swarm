"""Swarm production-pipeline dispatch queue.

Handoff layer between swarm sessions and the deterministic video pipeline,
per the production-pipeline-v1 spec ratified in Session 62. Phase 4
(image-review) owner writes a payload here when image review passes;
the systemd swarm-dispatch.path unit watches the queued/ directory and
triggers scripts/run_dispatch.py, which moves the file through
processing/ → done/ or failed/ as it executes the pipeline.

State machine (filesystem is the source of truth):

    queued/<id>.json   → submitted, awaiting runner pickup
    processing/<id>.json → runner has claimed it
    done/<id>.json + done/<id>.manifest.json   → pipeline succeeded
    failed/<id>.json + failed/<id>.manifest.json → pipeline failed

State transitions are atomic os.replace() calls on the same filesystem,
so a crashed runner leaves things in processing/ rather than corrupting
the queue. A startup-time sweep (handled by the runner) can re-queue
processing/ items if needed.

This module owns:
  - Path resolution under <storage_root>/swarm/dispatch/
  - Schema validation (minimal, hand-rolled — no jsonschema dep)
  - Atomic state transitions
  - Listing for /dispatch/status

Read scripts/run_dispatch.py for the runner.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import swarm_filestore

logger = logging.getLogger("SwarmVault")

QUEUED = "queued"
PROCESSING = "processing"
DONE = "done"
FAILED = "failed"
STATES = (QUEUED, PROCESSING, DONE, FAILED)

DISPATCH_VERSION = "1"

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_ID_SAFE_CHARS_RE = re.compile(r"[^a-zA-Z0-9]+")


# ============================================================
# Paths
# ============================================================

def _dispatch_root() -> Path:
    """Resolve the dispatch tree under the swarm filestore. Idempotently
    creates all four state directories on first call."""
    root = swarm_filestore._storage_root() / "dispatch"
    for state in STATES:
        (root / state).mkdir(parents=True, exist_ok=True)
    return root


def _payload_path(state: str, dispatch_id: str) -> Path | None:
    if state not in STATES or not _SAFE_ID_RE.match(dispatch_id):
        return None
    return _dispatch_root() / state / f"{dispatch_id}.json"


def _manifest_path(state: str, dispatch_id: str) -> Path | None:
    if state not in (DONE, FAILED) or not _SAFE_ID_RE.match(dispatch_id):
        return None
    return _dispatch_root() / state / f"{dispatch_id}.manifest.json"


# ============================================================
# Schema validation
# ============================================================

def validate_payload(payload: dict) -> tuple[bool, str | None]:
    """Minimal schema check. Returns (ok, error_message).

    Required:
      dispatch_version: "1"
      submitted_at:     ISO-8601 string
      submitted_by:     non-empty string (e.g., "swarm-session-62/claude/phase-4")
      script:           object with non-empty 'panels' list (matches the
                        existing /scripted-episode payload shape)

    Optional:
      callback_email:                str (defaults to RRI_CONDUCTOR_EMAIL)
      callback_email_subject_prefix: str
      notes:                         str (free-form, not used by runner)
    """
    if not isinstance(payload, dict):
        return False, "payload must be a JSON object"

    if payload.get("dispatch_version") != DISPATCH_VERSION:
        return False, (
            f"dispatch_version must be {DISPATCH_VERSION!r}, "
            f"got {payload.get('dispatch_version')!r}"
        )

    for field in ("submitted_at", "submitted_by", "script"):
        if field not in payload:
            return False, f"missing required field: {field}"

    if not isinstance(payload["submitted_at"], str) or not payload["submitted_at"].strip():
        return False, "submitted_at must be non-empty ISO-8601 string"
    if not isinstance(payload["submitted_by"], str) or not payload["submitted_by"].strip():
        return False, "submitted_by must be non-empty string"

    script = payload["script"]
    if not isinstance(script, dict):
        return False, "script must be an object"
    panels = script.get("panels")
    if not isinstance(panels, list) or not panels:
        return False, "script.panels must be a non-empty list"
    for i, panel in enumerate(panels):
        if not isinstance(panel, dict):
            return False, f"script.panels[{i}] must be an object"
        if "index" not in panel:
            return False, f"script.panels[{i}] missing 'index'"

    cb = payload.get("callback_email")
    if cb is not None and not isinstance(cb, str):
        return False, "callback_email must be string or omitted"

    return True, None


# ============================================================
# ID generation
# ============================================================

def _safe_id(submitted_by: str, episode: str | int | None) -> str:
    """Build a filesystem-safe dispatch id: <ts>_<episode>_<submitter>.

    Sanitizes both submitted_by and episode to [a-zA-Z0-9_-] chars only,
    so a malicious or sloppy caller can't break out of the dispatch dir.
    """
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    ep = ""
    if episode:
        ep_clean = _ID_SAFE_CHARS_RE.sub("-", str(episode)).strip("-")
        if ep_clean:
            ep = f"_{ep_clean[:32]}"
    sub_clean = _ID_SAFE_CHARS_RE.sub("-", submitted_by).strip("-")[:32]
    return f"{ts}{ep}_{sub_clean or 'unknown'}"


# ============================================================
# Public ops — write, transition, read, list
# ============================================================

def write_payload(payload: dict, submitted_by: str = "unknown") -> dict:
    """Validate and write a dispatch payload into queued/.

    Auto-fills dispatch_version, submitted_at, submitted_by if missing,
    so a model-emitted payload can be terse.

    Returns {ok, dispatch_id, path, error}.
    """
    payload = dict(payload)  # defensive copy
    payload.setdefault("dispatch_version", DISPATCH_VERSION)
    payload.setdefault("submitted_at", datetime.now().isoformat(timespec="seconds"))
    payload.setdefault("submitted_by", submitted_by)

    ok, err = validate_payload(payload)
    if not ok:
        return {"ok": False, "error": err}

    root = _dispatch_root()
    script = payload.get("script", {})
    episode = script.get("project_slug") or script.get("episode") or script.get("title")
    dispatch_id = _safe_id(payload["submitted_by"], episode)
    target = root / QUEUED / f"{dispatch_id}.json"

    try:
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        os.replace(tmp, target)
    except OSError as e:
        return {"ok": False, "error": f"write failed: {e}"}

    logger.info(f"swarm_dispatch queued {dispatch_id} from {payload['submitted_by']!r}")
    rel = str(target.relative_to(swarm_filestore._storage_root()))
    return {"ok": True, "dispatch_id": dispatch_id, "path": rel}


def transition(dispatch_id: str, from_state: str, to_state: str) -> Path | None:
    """Atomically move a dispatch payload between states.

    Returns the destination Path on success, None on failure (file missing,
    invalid id, or invalid state). Used by the runner.
    """
    if from_state not in STATES or to_state not in STATES:
        return None
    src = _payload_path(from_state, dispatch_id)
    dst = _payload_path(to_state, dispatch_id)
    if src is None or dst is None or not src.exists():
        return None
    try:
        os.replace(src, dst)
    except OSError as e:
        logger.error(f"swarm_dispatch transition {dispatch_id} {from_state}→{to_state} failed: {e}")
        return None
    logger.info(f"swarm_dispatch {dispatch_id}: {from_state} → {to_state}")
    return dst


def read_payload(state: str, dispatch_id: str) -> dict | None:
    p = _payload_path(state, dispatch_id)
    if p is None or not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"swarm_dispatch read_payload {state}/{dispatch_id}: {e}")
        return None


def write_result_manifest(dispatch_id: str, state: str, manifest: dict) -> None:
    """Write a sidecar manifest (e.g., done/<id>.manifest.json) recording
    pipeline stages, video path, errors. Called by the runner after the
    payload has been transitioned to done/ or failed/."""
    p = _manifest_path(state, dispatch_id)
    if p is None:
        return
    try:
        p.write_text(json.dumps(manifest, indent=2, default=str))
    except OSError as e:
        logger.error(f"swarm_dispatch write_result_manifest {dispatch_id}: {e}")


def list_state(state: str, limit: int = 50) -> list[dict]:
    if state not in STATES:
        return []
    root = _dispatch_root()
    items = []
    for p in sorted((root / state).glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.suffix == ".tmp" or p.name.endswith(".manifest.json"):
            continue
        stat = p.stat()
        items.append({
            "dispatch_id": p.stem,
            "size_bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "state": state,
            "has_manifest": (p.parent / f"{p.stem}.manifest.json").exists(),
        })
        if len(items) >= limit:
            break
    return items


def status() -> dict:
    return {
        "dispatch_root": str(_dispatch_root()),
        "version": DISPATCH_VERSION,
        "counts": {state: len(list_state(state, limit=10_000)) for state in STATES},
        "recent": {state: list_state(state, limit=10) for state in STATES},
    }
