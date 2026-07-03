#!/usr/bin/env python3
"""File queued Joy Mode tool proposals as GitHub issues (the autonomy handoff).

Joy Mode's tiny-tool-invention activity queues a structured proposal under
swarm/joy/proposals/queued/ (see swarm_proposals.py). This runner turns each
queued proposal into a GitHub issue for human review, then moves it to filed/.

The autonomy split: filing an issue is free and changes nothing that runs, so
it needs no approval. The GATED step — merging the proposed tool into the live
registry — stays a human-reviewed PR. Every filed issue carries that gate banner.

Filing backends, in order of preference:
  1. GitHub API — if RRI_GITHUB_PROPOSAL_TOKEN + RRI_GITHUB_PROPOSAL_REPO are
     set. Use a FINE-GRAINED token scoped to Issues: write on that ONE repo.
  2. Email — else, if swarm_mail is configured, email the Conductor the
     ready-to-paste issue title + body.
  3. Neither — leave the proposal in queued/ and log loudly (nothing lost).

Triggered by the systemd swarm-proposals.path unit when a file lands in
queued/. Manual:
  file_proposals.py            # file everything queued
  file_proposals.py --dry-run  # print what would be filed, transition nothing
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_VENV_PY = REPO_ROOT / "venv" / "bin" / "python3"
if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    print(f"WARNING: python-dotenv not importable in {sys.executable}; .env not loaded.",
          file=sys.stderr)

import swarm_proposals  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("proposal-filer")

GITHUB_API = "https://api.github.com"


def _file_via_github(issue: dict, token: str, repo: str) -> "tuple[bool, str]":
    """POST one issue to the GitHub REST API. Returns (ok, detail)."""
    url = f"{GITHUB_API}/repos/{repo}/issues"
    payload = {"title": issue["title"], "body": issue["body"]}
    labels = [l.strip() for l in os.environ.get("RRI_GITHUB_PROPOSAL_LABELS", "").split(",") if l.strip()]
    if labels:
        payload["labels"] = labels
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "raccoon-swarm-proposal-filer",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, data.get("html_url", "(created)")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        return False, f"HTTP {e.code}: {body}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, f"{type(e).__name__}: {e}"


def _file_via_email(issue: dict, proposal_id: str) -> "tuple[bool, str]":
    """Fallback: email the Conductor the ready-to-paste issue."""
    try:
        import swarm_mail
    except ImportError:
        return False, "swarm_mail unavailable"
    body = (
        "The swarm autonomously designed a tool during Joy Mode. No GitHub token "
        "is configured, so here is the proposal to file manually.\n\n"
        f"--- ISSUE TITLE ---\n{issue['title']}\n\n--- ISSUE BODY ---\n{issue['body']}"
    )
    try:
        ok, reason = swarm_mail.send_to_conductor(
            subject=f"Joy Mode tool proposal — {issue['title']}",
            body=body, model="proposal-filer", session_id=f"proposal-{proposal_id}")
        return ok, reason
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def file_one(proposal_id: str, *, dry_run: bool = False) -> bool:
    """File a single queued proposal. Returns True on success."""
    record = swarm_proposals.read_proposal(swarm_proposals.QUEUED, proposal_id)
    if record is None:
        logger.warning(f"{proposal_id}: not in queued/ (already filed?), skipping")
        return False

    issue = swarm_proposals.format_issue(record)
    token = os.environ.get("RRI_GITHUB_PROPOSAL_TOKEN", "").strip()
    repo = os.environ.get("RRI_GITHUB_PROPOSAL_REPO", "").strip()

    if dry_run:
        backend = "github" if (token and repo) else "email"
        logger.info(f"[dry-run] would file {proposal_id} via {backend}: {issue['title']}")
        return True

    if token and repo:
        ok, detail = _file_via_github(issue, token, repo)
        backend = "github"
    else:
        ok, detail = _file_via_email(issue, proposal_id)
        backend = "email"

    if ok:
        swarm_proposals.transition(proposal_id, swarm_proposals.QUEUED, swarm_proposals.FILED)
        logger.info(f"{proposal_id}: filed via {backend} — {detail}")
        return True

    # Leave GitHub failures in queued/ for retry on the next trigger; a bad
    # proposal that can never file would loop, so only move to failed/ when the
    # backend was actually reachable-but-rejected (HTTP 4xx), not on transport.
    if backend == "github" and detail.startswith("HTTP 4"):
        swarm_proposals.transition(proposal_id, swarm_proposals.QUEUED, swarm_proposals.FAILED)
        logger.error(f"{proposal_id}: rejected by GitHub, moved to failed/ — {detail}")
    else:
        logger.error(f"{proposal_id}: filing failed ({backend}), left in queued/ — {detail}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="File queued Joy Mode tool proposals.")
    parser.add_argument("proposal_id", nargs="?", help="File one specific proposal id.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be filed without transitioning anything.")
    args = parser.parse_args()

    if args.proposal_id:
        return 0 if file_one(args.proposal_id, dry_run=args.dry_run) else 1

    queued = swarm_proposals.list_state(swarm_proposals.QUEUED, limit=10_000)
    if not queued:
        logger.info("no queued proposals")
        return 0
    failures = 0
    for item in queued:
        if not file_one(item["proposal_id"], dry_run=args.dry_run):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
