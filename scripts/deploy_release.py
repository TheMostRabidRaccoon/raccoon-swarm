#!/usr/bin/env python3
"""Staged release deployer — GitHub main is authoritative, the server is
non-authoring, and no code changes under the live service until it has
passed the full test suite plus a boot smoke test in a staged worktree.

Born from the 2026-07-13 deploy gap: the image-disclosure fix was merged to
main roughly an hour BEFORE Session 142 falsely convicted the image pipeline
that fix repaired — merged-but-not-deployed sat invisible for eleven days.
This script makes drift visible (--check) and makes deployment staged,
locked, health-checked, receipted, and rolled back on failure.

Usage:
  ./scripts/deploy_release.py --check          # read-only drift report
  ./scripts/deploy_release.py --latest --yes   # deploy live upstream main
  ./scripts/deploy_release.py --to <sha> --yes # deploy an exact commit

Flow: fetch → resolve target (must be on origin/main) → staged worktree at
target SHA → full pytest suite + import/boot smoke there → ff-only promote
of the live checkout → daemon restart (kill; systemd respawns — no sudo on
this box) → health check against /version boot SHA → automatic rollback to
the prior SHA on any failure → JSON receipt appended to logs/deployments.log.

Unattended auto-deploy is DELIBERATELY not implemented: run this by hand
until several releases in a row have clean receipts.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STAGE_ROOT = REPO.parent / "deploy-stage"
VENV_PY = REPO / "venv" / "bin" / "python3"
HEALTH_URL = "http://localhost:5000/version"
HEALTH_TIMEOUT_S = 90
SERVICE = "swarm"


def run(cmd: list[str], cwd: Path = REPO, timeout: int = 120, env: dict | None = None,
        check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       timeout=timeout, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed rc={r.returncode}:\n"
                           f"{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return r


def git(*args: str, cwd: Path = REPO, timeout: int = 120, check: bool = True):
    return run(["git", *args], cwd=cwd, timeout=timeout, check=check)


def storage_logs_dir() -> Path:
    """Resolve <storage_root>/swarm/logs the same way the server does:
    RRI_STORAGE_DIR from the environment or the live .env, else the repo."""
    root = os.environ.get("RRI_STORAGE_DIR")
    if not root:
        env_file = REPO / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.strip().startswith("RRI_STORAGE_DIR="):
                    root = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    base = Path(root) if root else REPO
    return base / "swarm" / "logs"


def http_version(timeout: float = 5.0) -> dict | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def upstream_main_sha() -> str:
    r = git("ls-remote", "origin", "refs/heads/main", timeout=30)
    fields = r.stdout.split()
    if not fields:
        raise RuntimeError("ls-remote returned nothing — is GitHub reachable?")
    return fields[0]


def check_report() -> int:
    """Read-only drift report. Compares the RUNNING process (via /version),
    the checked-out HEAD, and live upstream main. Never mutates anything."""
    head = git("rev-parse", "HEAD").stdout.strip()
    upstream = upstream_main_sha()
    v = http_version()
    running = (v or {}).get("boot_commit")
    print(f"running (daemon): {running or 'daemon unreachable'}")
    print(f"checkout (HEAD):  {head[:12]}")
    print(f"upstream (main):  {upstream[:12]}")
    if running and upstream.startswith(running):
        print("status: IN SYNC — the daemon runs live upstream main")
        return 0
    if running and head.startswith(running) and head != upstream:
        print("status: DRIFT — upstream main has moved; a deploy is owed")
    elif running and not head.startswith(running):
        print("status: STALE PROCESS — checkout advanced without a restart")
    else:
        print("status: UNKNOWN — daemon unreachable; compare SHAs manually")
    return 1


def restart_daemon() -> None:
    """No passwordless sudo on this box: kill the MainPID and let systemd
    Restart=always respawn it."""
    pid = run(["systemctl", "show", "-p", "MainPID", "--value", SERVICE]).stdout.strip()
    if pid and pid != "0":
        run(["kill", pid], check=False)


def wait_healthy(expect_sha: str) -> tuple[bool, str]:
    """Healthy = systemd active + /version answers + boot_commit == target."""
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    last = "no response yet"
    while time.monotonic() < deadline:
        time.sleep(3)
        active = run(["systemctl", "is-active", SERVICE], check=False).stdout.strip()
        if active != "active":
            last = f"service state: {active}"
            continue
        v = http_version()
        if v is None:
            last = "service active, /version not answering"
            continue
        boot = v.get("boot_commit") or ""
        if expect_sha.startswith(boot) and boot:
            return True, f"healthy: boot_commit={boot}"
        last = f"answering but boot_commit={boot!r} != target"
    return False, last


def stage_and_test(sha: str) -> dict:
    """Create a detached worktree at `sha` and run the full suite plus an
    import/boot smoke test there. The live checkout is untouched."""
    STAGE_ROOT.mkdir(exist_ok=True)
    stage = STAGE_ROOT / sha[:12]
    if stage.exists():
        git("worktree", "remove", "--force", str(stage), check=False)
    git("worktree", "add", "--detach", str(stage), sha)

    env = dict(os.environ, PYTHONPATH=str(stage))
    result: dict = {}
    try:
        t = run([str(VENV_PY), "-m", "pytest", "tests/", "-q"],
                cwd=stage, timeout=600, env=env, check=False)
        tail = (t.stdout.strip().splitlines() or ["no output"])[-1]
        result["tests"] = {"passed": t.returncode == 0, "summary": tail}
        if t.returncode != 0:
            result["tests"]["output_tail"] = (t.stdout + t.stderr)[-3000:]
            return result

        # Boot smoke: can the server module even import under the live .env?
        # (Catches broken imports and fail-closed deploy-profile refusals that
        # unit tests, which skip the main module, would miss.)
        smoke_code = (
            "from dotenv import load_dotenv; "
            f"load_dotenv(r'{REPO / '.env'}'); "
            "import raccoon_swarm_server; print('boot import OK')"
        )
        s = run([str(VENV_PY), "-c", smoke_code], cwd=stage, timeout=180,
                env=env, check=False)
        result["boot_smoke"] = {"passed": s.returncode == 0 and "boot import OK" in s.stdout}
        if not result["boot_smoke"]["passed"]:
            result["boot_smoke"]["output_tail"] = (s.stdout + s.stderr)[-3000:]
        return result
    finally:
        git("worktree", "remove", "--force", str(stage), check=False)


def write_receipt(receipt: dict) -> None:
    logs = storage_logs_dir()
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "deployments.log", "a") as f:
        f.write(json.dumps(receipt) + "\n")


def deploy(target: str, assume_yes: bool) -> int:
    receipt: dict = {"ts": datetime.now().isoformat(timespec="seconds"),
                     "target": target[:12], "result": "aborted"}
    prev = git("rev-parse", "HEAD").stdout.strip()
    receipt["previous"] = prev[:12]

    # Refuse to deploy over local authorship — the server is non-authoring.
    dirty = git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        print("ABORT: live checkout has uncommitted tracked changes:\n" + dirty)
        print("The server is non-authoring — land changes via GitHub main.")
        write_receipt(receipt | {"reason": "dirty checkout"})
        return 1

    git("fetch", "origin", timeout=120)  # also refreshes the tracking ref
    if not git("merge-base", "--is-ancestor", target, "origin/main",
               check=False).returncode == 0:
        print(f"ABORT: {target[:12]} is not on origin/main — only published "
              f"commits are deployable.")
        write_receipt(receipt | {"reason": "target not on origin/main"})
        return 1

    if prev == target:
        v = http_version()
        if v and target.startswith(v.get("boot_commit") or "\0"):
            print("Nothing to do: daemon already runs this commit.")
            return 0
        print("Checkout already at target; restarting daemon to load it.")

    req_diff = git("diff", "--name-only", f"{prev}..{target}", "--",
                   "requirements.txt", check=False).stdout.strip()
    if req_diff:
        print("WARNING: requirements.txt changed in this release; the shared "
              "venv may need a pip install. Staged tests will tell.")

    if not assume_yes:
        answer = input(f"Deploy {target[:12]} (currently {prev[:12]})? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("aborted by operator")
            return 1

    print(f"staging {target[:12]} …")
    stage_result = stage_and_test(target)
    receipt.update(stage_result)
    if not stage_result.get("tests", {}).get("passed"):
        print("ABORT: staged test suite failed — live code untouched.")
        print(stage_result["tests"].get("output_tail", ""))
        write_receipt(receipt | {"result": "staged-tests-failed"})
        return 1
    if not stage_result.get("boot_smoke", {}).get("passed"):
        print("ABORT: staged boot smoke failed — live code untouched.")
        print(stage_result["boot_smoke"].get("output_tail", ""))
        write_receipt(receipt | {"result": "staged-boot-smoke-failed"})
        return 1
    print(f"staged checks green ({stage_result['tests']['summary']}); promoting …")

    git("merge", "--ff-only", target)
    restart_daemon()
    ok, detail = wait_healthy(target)
    receipt["health"] = detail
    if ok:
        receipt["result"] = "deployed"
        write_receipt(receipt)
        print(f"DEPLOYED {target[:12]} — {detail}")
        return 0

    print(f"HEALTH CHECK FAILED ({detail}); rolling back to {prev[:12]} …")
    git("reset", "--hard", prev)
    restart_daemon()
    rb_ok, rb_detail = wait_healthy(prev)
    receipt["result"] = "rolled-back" if rb_ok else "ROLLBACK-FAILED"
    receipt["rollback_health"] = rb_detail
    write_receipt(receipt)
    print(f"rollback {'succeeded' if rb_ok else 'FAILED — manual intervention needed'}: {rb_detail}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="read-only drift report")
    g.add_argument("--latest", action="store_true", help="deploy live upstream main")
    g.add_argument("--to", metavar="SHA", help="deploy an exact commit")
    ap.add_argument("--yes", action="store_true", help="skip confirmation prompt")
    args = ap.parse_args()

    if args.check:
        return check_report()

    lock = open(REPO / ".deploy.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("ABORT: another deploy is already running (.deploy.lock held)")
        return 1

    git("fetch", "origin", timeout=120)
    if args.latest:
        target = upstream_main_sha()
    else:
        target = git("rev-parse", args.to).stdout.strip()
    return deploy(target, assume_yes=args.yes)


if __name__ == "__main__":
    sys.exit(main())
