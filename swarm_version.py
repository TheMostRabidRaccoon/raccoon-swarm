"""Runtime version reporting — 'merged ≠ deployed' made detectable.

Session 133 surfaced the hazard: a fix can be merged to `main` (and every seat
can verify it there) while the *running server* is still executing pre-merge
code, because nobody restarted the process after the merge. The swarm is
GOVERNED by main but OPERATED by whatever bytecode is loaded. A claim
"verified against main" says nothing about the runtime the swarm actually lives
in.

The fix is a boot anchor. `BOOT_COMMIT` is captured ONCE at import — i.e. when
the server process starts — so it reflects the code the process actually loaded.
A live `git rev-parse` reads the *working tree* HEAD, which a `git pull` can
advance without restarting the process. When the two disagree, the process is
running stale code and needs a restart. `/version` exposes both so seats and ops
can pin against the DEPLOYED commit, not the repo's.

Stdlib only; git calls are best-effort and never raise.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path


def _read_head_sha() -> "str | None":
    """Short SHA of the working-tree HEAD. RRI_REPO_SHA overrides (containers
    without git on PATH). Never raises."""
    env = os.environ.get("RRI_REPO_SHA")
    if env:
        return env.strip()[:12]
    try:
        here = Path(__file__).resolve().parent
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=5)
        sha = out.stdout.strip()
        return sha or None
    except Exception:
        return None


# Captured ONCE, at process boot (import time). This is the deployed commit —
# the code the running process actually loaded. Do not recompute it live.
BOOT_COMMIT = _read_head_sha()
BOOT_TIME = datetime.now().isoformat(timespec="seconds")


def compute_up_to_date(boot: "str | None", head: "str | None") -> "bool | None":
    """True if the running process matches the checked-out code, False if it's
    behind (restart needed), None if either SHA is unknown (can't tell)."""
    if boot is None or head is None:
        return None
    return boot == head


def version_info() -> dict:
    """What /version returns: the boot (deployed) commit vs the live checked-out
    commit, and whether they match. `up_to_date: false` means the working tree
    advanced past the running process — restart to deploy the merged code."""
    head = _read_head_sha()
    up = compute_up_to_date(BOOT_COMMIT, head)
    return {
        "boot_commit": BOOT_COMMIT,     # what the running process loaded
        "head_commit": head,            # what's checked out right now
        "up_to_date": up,               # false => merged-but-not-deployed
        "boot_time": BOOT_TIME,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "note": (None if up is not False else
                 "running process is BEHIND the checkout — restart to deploy merged code"),
    }
