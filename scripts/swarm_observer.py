#!/usr/bin/env python3
# ruff: noqa: E402
"""swarm_observer — weekly cross-session digest for the Conductor.

Reads the swarm filestore (~/raccoon-swarm/swarm/ by default) plus recent
persistence audits, sends the lot to Claude via the Anthropic SDK, and
produces a structured digest covering four buckets:

  1. Gaps & misses        — decisions in conversation never written;
                             cross-session threads that keep reappearing
  2. Dynamic health       — persona drift; recurring disagreements
  3. Emergent terminology — concepts the swarm coined that keep recurring
  4. Productivity audit   — sessions that produced artifacts vs atmosphere

Output:
  - Local markdown at ~/raccoon-swarm/observer-reports/YYYY-MM-DD_digest.md
  - Email to RRI_CONDUCTOR_EMAIL via direct SMTP (bypasses the swarm's
    rate-limited mail channel — observer emails are an independent channel)

CRITICAL: the observer writes only to the Conductor. It does NOT write to
the swarm filestore. The swarm does not see its output. This keeps the
swarm's reflexive audit loop separate from the human curation layer.

Usage:
  ./scripts/swarm_observer.py                # last 7 days, write + email
  ./scripts/swarm_observer.py --days 30      # last 30 days
  ./scripts/swarm_observer.py --dry-run      # write local file, don't email
  ./scripts/swarm_observer.py --no-write     # email only, no local file

Cron suggestion (weekly Sunday 8am):
  0 8 * * 0 cd ~/raccoon-swarm && ./scripts/swarm_observer.py >> ~/observer.log 2>&1
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Self-bootstrap into the swarm's venv if we're not already there. Looks for
# {repo_root}/venv/bin/python3 next to this script's parent dir. Means the
# script "just works" via `./scripts/swarm_observer.py` without remembering
# `source venv/bin/activate` — and cron entries don't need venv-activation
# wrappers either.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENV_PYTHON = _REPO_ROOT / "venv" / "bin" / "python3"
if _VENV_PYTHON.exists() and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), __file__, *sys.argv[1:]])

import argparse
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass


SWARM_ROOT = Path(os.getenv("SWARM_ROOT") or Path.home() / "raccoon-swarm" / "swarm")
REPORTS_DIR = Path(os.getenv("OBSERVER_REPORTS_DIR") or Path.home() / "raccoon-swarm" / "observer-reports")
MODEL = os.getenv("OBSERVER_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = int(os.getenv("OBSERVER_MAX_TOKENS", "6000"))


def gather_inputs(days: int) -> dict:
    """Walk the filestore for content the observer should read."""
    cutoff = datetime.now() - timedelta(days=days)
    inputs: dict = {
        "window_days": days,
        "filestore_root": str(SWARM_ROOT),
        "persistence_audits": [],
        "positions": [],
        "frameworks": [],
        "recent_artifacts": [],
        "image_attribution": "",
        "all_files_in_window": [],
    }

    if not SWARM_ROOT.exists():
        return inputs

    def _recent(path: Path) -> bool:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime) >= cutoff
        except OSError:
            return False

    logs_dir = SWARM_ROOT / "logs"
    if logs_dir.exists():
        for f in sorted(logs_dir.glob("*persistence-audit*.md")):
            if _recent(f):
                inputs["persistence_audits"].append({
                    "path": str(f.relative_to(SWARM_ROOT)),
                    "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "content": f.read_text(errors="replace")[:30_000],
                })
        img_log = logs_dir / "image-generations.log"
        if img_log.exists():
            inputs["image_attribution"] = img_log.read_text(errors="replace")[-10_000:]

    for subdir in ("positions", "frameworks"):
        d = SWARM_ROOT / subdir
        if d.exists():
            for f in sorted(d.rglob("*.md")):
                inputs[subdir].append({
                    "path": str(f.relative_to(SWARM_ROOT)),
                    "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "content": f.read_text(errors="replace")[:5_000],
                })

    artifacts = SWARM_ROOT / "artifacts"
    if artifacts.exists():
        for f in sorted(artifacts.rglob("*")):
            if not f.is_file() or "/code-runs/" in str(f) or "/images/" in str(f):
                continue
            if _recent(f) and f.suffix in {".md", ".json", ".txt"}:
                inputs["recent_artifacts"].append({
                    "path": str(f.relative_to(SWARM_ROOT)),
                    "mtime": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    "content": f.read_text(errors="replace")[:8_000],
                })

    for f in sorted(SWARM_ROOT.rglob("*")):
        if not f.is_file() or "/code-runs/" in str(f):
            continue
        if _recent(f):
            inputs["all_files_in_window"].append(str(f.relative_to(SWARM_ROOT)))

    return inputs


SYSTEM_PROMPT = """You are the Swarm Observer for Rabid Raccoon Intelligence's
multi-model AI swarm. The swarm is five named models (Claude, Grok, Gemini, GPT,
Perplexity) that deliberate in rounds and write decisions, artifacts, and
positions to a shared filestore. Each session has a Persistence Audit that
reviews what got written. Your job is the layer above: read ACROSS sessions and
surface patterns no single session can see, because each session is mortal and
the swarm only remembers what got written.

You produce a digest for one human reader (the Conductor, Kyra). The swarm does
NOT see your output. You are not in the swarm's reflexive loop. Your goal is
honest observation, not encouragement.

Cover four buckets. Be specific. Quote brief snippets. Cite filestore paths.

  1. GAPS & MISSES
     - Decisions visible in conversation/synthesis text that don't have a
       corresponding /positions/ or /frameworks/ file.
     - Topics that appear in 3+ sessions and have not resolved. Name them.
     - Email triggers ([REVIEW] / [BLOCKER] / [FLAG]) that look like they were
       met in the transcript but never sent.

  2. DYNAMIC HEALTH
     - Persona drift per raccoon: is Grok still chaotic and contrarian, is
       Claude still rigorous, is Gemini still bardic, is GPT still
       integrative, is Perplexity still citation-grounded? Flag drift early.
     - Recurring disagreements between specific raccoons. Distinguish
       productive tension (sharp ideas) from stuck tension (going in circles).

  3. EMERGENT TERMINOLOGY
     - New concepts/terms/phrases the swarm coined recently that recur.
       "Existence Criterion" is the worked example: it started as a swarm
       proposal and became ratified law. Catch the next one earlier.

  4. PRODUCTIVITY AUDIT
     - Which sessions produced lasting artifacts (referenced later, ratified
       as positions) versus which produced atmosphere (enjoyable conversation
       that evaporated). Be honest. Atmosphere has value but not unbounded.

After the four buckets, produce:

  5. RECOMMENDED CONDUCTOR ACTIONS
     - [REVIEW] — artifacts the Conductor should look at this week, with
       filestore paths.
     - [BLOCKER] — decisions only the Conductor can resolve that are
       blocking work.
     - [FLAG] — anything the Conductor would want to know happened.
     Use the same prefix taxonomy the swarm uses. Be sparing.

  6. ONE-LINE TL;DR at the very top of the document.

Format as markdown. Be direct. No hedging. No "great question." No flattery.
The Conductor's time is the scarce resource."""


def build_user_message(inputs: dict) -> str:
    lines: list[str] = [
        f"# Observer input bundle ({inputs['window_days']}-day window)",
        f"Filestore root: {inputs['filestore_root']}",
        f"Files written in window: {len(inputs['all_files_in_window'])}",
        "",
        "## Persistence audits (newest last)",
    ]
    for a in inputs["persistence_audits"]:
        lines += [f"\n### {a['path']}  ({a['mtime']})", "```", a["content"], "```"]
    if not inputs["persistence_audits"]:
        lines.append("(none in window)")

    lines += ["\n## Positions (full current state)"]
    for p in inputs["positions"]:
        lines += [f"\n### {p['path']}", "```", p["content"], "```"]
    if not inputs["positions"]:
        lines.append("(none)")

    lines += ["\n## Frameworks (full current state)"]
    for fw in inputs["frameworks"]:
        lines += [f"\n### {fw['path']}", "```", fw["content"], "```"]
    if not inputs["frameworks"]:
        lines.append("(none)")

    lines += ["\n## Recent artifacts (md/json/txt only, excluding code-runs + images)"]
    for art in inputs["recent_artifacts"]:
        lines += [f"\n### {art['path']}  ({art['mtime']})", "```", art["content"], "```"]
    if not inputs["recent_artifacts"]:
        lines.append("(none in window)")

    if inputs["image_attribution"]:
        lines += [
            "\n## Image-generations.log (tail — for attribution)",
            "```",
            inputs["image_attribution"],
            "```",
        ]

    lines += [
        "\n## File-tree of everything written in window",
        "```",
        "\n".join(inputs["all_files_in_window"]) or "(empty)",
        "```",
        "",
        "Produce the digest now. Cover all four buckets, then the Recommended Actions, then the TL;DR at the top. Markdown.",
    ]
    return "\n".join(lines)


def call_claude(user_message: str) -> str:
    try:
        import anthropic
    except ImportError:
        print("error: anthropic SDK not installed. pip install anthropic", file=sys.stderr)
        sys.exit(2)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(2)
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def email_digest(digest: str, dest_path: Path) -> tuple[bool, str]:
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT", "587")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_APP_PASSWORD")
    recipient = os.getenv("RRI_CONDUCTOR_EMAIL")
    if not all([host, user, password, recipient]):
        return False, "SMTP not fully configured (SMTP_HOST/USER/APP_PASSWORD/RRI_CONDUCTOR_EMAIL)"

    today = datetime.now().strftime("%Y-%m-%d")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[OBSERVER] Weekly swarm digest — {today}"
    msg["From"] = f"Swarm Observer <{user}>"
    msg["To"] = recipient
    body = f"Local copy: {dest_path}\n\n{digest}"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(host, int(port), timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        return True, f"sent to {recipient}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=7, help="Window in days (default 7)")
    parser.add_argument("--dry-run", action="store_true", help="Write local file; do not email")
    parser.add_argument("--no-write", action="store_true", help="Email only; do not write local file")
    parser.add_argument("--output", type=Path, default=None, help="Override local output path")
    args = parser.parse_args()

    print(f"🦝 swarm_observer — {args.days}-day window")
    print(f"   filestore: {SWARM_ROOT}")
    inputs = gather_inputs(args.days)
    print(f"   audits: {len(inputs['persistence_audits'])}, "
          f"positions: {len(inputs['positions'])}, "
          f"frameworks: {len(inputs['frameworks'])}, "
          f"recent artifacts: {len(inputs['recent_artifacts'])}, "
          f"files in window: {len(inputs['all_files_in_window'])}")
    if not any([inputs["persistence_audits"], inputs["positions"], inputs["frameworks"], inputs["recent_artifacts"]]):
        print("   nothing to observe — filestore is empty in this window. exiting.")
        return 0

    user_message = build_user_message(inputs)
    print(f"   prompt size: ~{len(user_message)} chars")
    print(f"   calling {MODEL}...")
    digest = call_claude(user_message)

    today = datetime.now().strftime("%Y-%m-%d")
    if not args.no_write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = args.output or REPORTS_DIR / f"{today}_digest.md"
        out_path.write_text(digest)
        print(f"   wrote {out_path}")
    else:
        out_path = Path("/dev/null")

    if not args.dry_run:
        ok, reason = email_digest(digest, out_path)
        print(f"   email: {'✓' if ok else '✗'} {reason}")
    else:
        print("   email: (skipped, --dry-run)")

    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
