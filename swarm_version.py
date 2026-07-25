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
import time
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


def _read_upstream_sha(timeout: float = 5.0) -> "str | None":
    """Short SHA of origin/main as the remote reports it RIGHT NOW (ls-remote).

    The cached origin/main tracking ref goes stale whenever commits arrive by
    bundle or side channel — on 2026-07-24 the server showed "ahead 7" against
    a week-old cache while actually in sync — so drift must be measured
    against the live remote, never the tracking ref. Anonymous read works
    while the repo is public. Never raises; None when offline or slow."""
    try:
        here = Path(__file__).resolve().parent
        out = subprocess.run(
            ["git", "-C", str(here), "ls-remote", "origin", "refs/heads/main"],
            capture_output=True, text=True, timeout=timeout)
        fields = out.stdout.split()
        return fields[0][:12] if fields else None
    except Exception:
        return None


_UPSTREAM_CACHE: dict = {"sha": None, "at": 0.0}
_UPSTREAM_TTL_S = 300.0


def upstream_sha(max_age_s: float = _UPSTREAM_TTL_S) -> "str | None":
    """TTL-cached upstream-main SHA. /version is unauthenticated, so the
    network probe must not run per request; five minutes of staleness is fine
    for a signal that previously went unmeasured for eleven days."""
    now = time.monotonic()
    if _UPSTREAM_CACHE["sha"] is not None and (now - _UPSTREAM_CACHE["at"]) < max_age_s:
        return _UPSTREAM_CACHE["sha"]
    sha = _read_upstream_sha()
    if sha is not None:
        _UPSTREAM_CACHE["sha"] = sha
        _UPSTREAM_CACHE["at"] = now
    return sha


def compute_drift(running: "str | None", upstream: "str | None") -> "bool | None":
    """True when the running process differs from live upstream main — a
    deploy (or restart) is owed. None = can't tell (offline / no git)."""
    if running is None or upstream is None:
        return None
    return running != upstream


def session_banner() -> str:
    """One-line version stamp for session context. The swarm should always
    know exactly which commit it is running and whether that commit is the
    one upstream main says it should be (the July 13 deploy gap: the image
    fix was merged ~1h before Session 142 convicted the pipeline it fixed)."""
    up = upstream_sha()
    drift = compute_drift(BOOT_COMMIT, up)
    if drift is None:
        state = "upstream unreachable — drift unknown"
    elif drift:
        state = (f"DRIFT: upstream main is {up} — this server is NOT running "
                 f"the latest merged code; a fix you verified on main may not "
                 f"be live here")
    else:
        state = "in sync with upstream main"
    return f"=== SERVER VERSION === running={BOOT_COMMIT or 'unknown'} ({state})"


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
    upstream = upstream_sha()
    return {
        "boot_commit": BOOT_COMMIT,     # what the running process loaded
        "head_commit": head,            # what's checked out right now
        "up_to_date": up,               # false => merged-but-not-deployed
        "running_sha": BOOT_COMMIT,     # canonical name for the deployed commit
        "upstream_sha": upstream,       # live origin/main via ls-remote (TTL-cached)
        "drift": compute_drift(BOOT_COMMIT, upstream),  # true => deploy owed
        "boot_time": BOOT_TIME,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "note": (None if up is not False else
                 "running process is BEHIND the checkout — restart to deploy merged code"),
    }
