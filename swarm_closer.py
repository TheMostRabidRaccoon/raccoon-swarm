"""Session Closer — fires after every synthesis save. Two jobs in v1:
emails the Conductor a digest of what happened, and writes a fallback
local markdown file if SMTP isn't configured.

Architecture: read-only against the filestore. The Closer doesn't make
filing decisions — it observes what just happened and tells you. Job 2
(persistence scrub backstop) lands in v2 once we've soaked v1 for a
couple of real sessions.

Trigger: called from loop_worker and headless_worker right after the
synthesis-directive parsing finishes. Runs on a daemon thread —
fire-and-forget. SMTP flakiness never blocks session completion.

Idempotency: marker file at OUTPUTS_DIR/{session_id}.closer-fired.json.
Re-running a session save is safe; the Closer logs "already fired" and
returns without sending or writing.

Disable: RRI_CLOSER_ENABLED=false (default true).

Family: per-iteration Round Orchestrator → end-of-session Closer →
weekly Observer. Same surveillance lineage, different cadences.
"""
from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import swarm_orchestrator

logger = logging.getLogger("SwarmVault")


def _enabled() -> bool:
    return os.getenv("RRI_CLOSER_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


# Audit COUNTS block from synthesis section 6 (PERSISTENCE AUDIT):
#   triggers_identified: <N>
#   emails_sent: <M>
#   gap: <K>
_COUNT_RE = re.compile(
    r"triggers_identified:\s*(\d+).*?emails_sent:\s*(\d+).*?gap:\s*(-?\d+)",
    re.DOTALL | re.IGNORECASE,
)

# [EMAIL_CONDUCTOR: [BLOCKER|REVIEW|FLAG] subject text]
# Matches the three-tier taxonomy from PERSISTENT_MEMORY_PROTOCOL.
_EMAIL_TAG_RE = re.compile(
    r"\[EMAIL_CONDUCTOR:\s*\[(BLOCKER|REVIEW|FLAG)\]\s*([^\]\n]+?)\]"
)

# Provider-side rate-limit indicators visible inside model output text.
# (Truncations are detected separately via swarm_orchestrator.)
_RATE_LIMIT_HINTS = ("429", "rate_limit", "rate limit", "ratelimit", "TooManyRequests")


def _parse_audit_counts(synthesis: str) -> Optional[dict]:
    if not synthesis:
        return None
    m = _COUNT_RE.search(synthesis)
    if not m:
        return None
    return {
        "triggers_identified": int(m.group(1)),
        "emails_sent": int(m.group(2)),
        "gap": int(m.group(3)),
    }


def _extract_email_directives(text: str) -> list[dict]:
    if not text:
        return []
    return [{"prefix": m.group(1), "subject": m.group(2).strip()}
            for m in _EMAIL_TAG_RE.finditer(text)]


# Bare tier-tagged items anywhere in the transcript — NOT only inside an
# [EMAIL_CONDUCTOR] directive. Lets the digest carry WHAT was flagged even when
# the swarm identified a trigger but never emitted a directive for it, so the
# Conductor still gets the substance instead of just a count. The {12,240}
# bound (and excluding brackets) skips incidental mentions like "a [FLAG] not a
# [REVIEW]" and only captures items with a real description.
_TRIGGER_ITEM_RE = re.compile(
    r"\[(BLOCKER|REVIEW|FLAG)\]\s*[:\-—]?\s*([^\n\[\]]{12,240})"
)


def _extract_trigger_items(*texts: str, limit: int = 12) -> list[dict]:
    """Pull tier-tagged items ([BLOCKER]/[REVIEW]/[FLAG]) from any text, deduped
    and capped. Surfaces the content behind the audit gap when no email fired."""
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for text in texts:
        if not text:
            continue
        for m in _TRIGGER_ITEM_RE.finditer(text):
            tier = m.group(1).upper()
            desc = m.group(2).strip().strip("*`").rstrip(".—-: ").strip()
            # Skip fragments that are punctuation-led (incidental mid-sentence
            # tag references rather than a real flagged item).
            if not desc or not desc[0].isalnum():
                continue
            key = (tier, desc.lower())
            if key in seen:
                continue
            seen.add(key)
            items.append({"tier": tier, "text": desc})
            if len(items) >= limit:
                return items
    return items


def _detect_rate_limits(round_results: dict) -> list[str]:
    hits = []
    for model, output in round_results.items():
        if model == "_meta" or not isinstance(output, str):
            continue
        for hint in _RATE_LIMIT_HINTS:
            if hint in output:
                hits.append(model)
                break
    return hits


def build_digest(
    *,
    query: str,
    all_rounds: list[dict],
    synthesis: str,
    session_id: str,
    fs_synth: Optional[dict] = None,
    mail_synth: Optional[dict] = None,
    duration: Optional[float] = None,
) -> dict:
    """Pure function: assemble the digest data from session inputs.
    Returns a dict ready to be formatted into an email body.
    """
    synthesis_directives = _extract_email_directives(synthesis or "")
    blockers = [d for d in synthesis_directives if d["prefix"] == "BLOCKER"]
    reviews = [d for d in synthesis_directives if d["prefix"] == "REVIEW"]
    flags = [d for d in synthesis_directives if d["prefix"] == "FLAG"]

    mail_sent = (mail_synth or {}).get("sent", []) or []
    mail_rejected = (mail_synth or {}).get("rejected", []) or []
    fs_writes = (fs_synth or {}).get("writes", []) or []
    fs_appends = (fs_synth or {}).get("appends", []) or []
    fs_rejected = (fs_synth or {}).get("rejected", []) or []

    counts = _parse_audit_counts(synthesis or "")

    # Tier-tagged items found across the synthesis + round transcript, regardless
    # of whether they became [EMAIL_CONDUCTOR] directives. This is what lets the
    # digest tell the Conductor *what* was flagged even when the email gap > 0.
    round_text = "\n".join(
        out for rd in all_rounds for m, out in rd.items()
        if m != "_meta" and isinstance(out, str)
    )
    trigger_items = _extract_trigger_items(synthesis or "", round_text)

    rounds_summary = []
    truncated_models: set[str] = set()
    rate_limited_models: set[str] = set()
    for i, rd in enumerate(all_rounds, 1):
        models = sorted(m for m in rd.keys() if m != "_meta")
        for m, _partial in swarm_orchestrator.detect_truncations(rd):
            truncated_models.add(m)
        for m in _detect_rate_limits(rd):
            rate_limited_models.add(m)
        rounds_summary.append({"round": i, "models": models})

    return {
        "session_id": session_id,
        "query": (query or "").strip(),
        "rounds": rounds_summary,
        "duration_sec": duration,
        "blockers": blockers,
        "reviews": reviews,
        "flags": flags,
        "mail_sent": mail_sent,
        "mail_rejected": mail_rejected,
        "fs_writes": fs_writes,
        "fs_appends": fs_appends,
        "fs_rejected": fs_rejected,
        "audit_counts": counts,
        "trigger_items": trigger_items,
        "truncated_models": sorted(truncated_models),
        "rate_limited_models": sorted(rate_limited_models),
    }


# ============================================================
# Session scorecard v0 — mechanical counters only
# ============================================================
#
# The measurement arc's first brick: a structured session_scorecard.json emitted
# beside every closer digest. MECHANICAL COUNTERS ONLY — no usefulness/quality
# self-grades. Judgment fields are excluded by design; they require an
# INDEPENDENT grader (an eval harness), never swarm self-report, or the
# scoreboard is just vibes with indentation.
#
# Emission is fail-LOUD, not fail-CLOSED: a scorecard write failure is logged
# but never discards the session's real work. That matches this module's own
# contract ("Failures are logged but never raised") — the synthesis is the
# product; the scorecard is the instrument, and a broken instrument must not
# nuke a completed session.

SCORECARD_VERSION = 1


def find_phantom_claims(all_rounds: list[dict], synthesis: str) -> "list[str] | None":
    """The DISTINCT filestore paths claimed-as-written across the rounds +
    synthesis that do NOT exist on disk — verify-then-emit, not trust-then-emit.

    Reuses swarm_filestore's phantom-write detector from #66: it finds every
    path a model claimed near a persistence cue, then checks the actual floor
    (read_file — an exact existence check, stronger than a substring search).
    The returned list IS the claimed-vs-found diff, and its length IS
    persistence_gap. Announcing a write is not a write.

    Returns None (NOT an empty list) if the detector itself fails — an empty
    list means "we checked and found none", None means "the flashlight dropped".
    The scorecard must not report persistence_gap 0 when it never actually
    measured.

    Call after writes have been persisted (the closer runs post-session). The
    returned paths are NAMED in the scorecard so the gap is actionable, not just
    a magnitude — this is what would have caught all three phantoms in the review
    session without anyone having to notice.
    """
    import swarm_filestore
    combined: dict = {}
    for i, rd in enumerate(all_rounds or []):
        for m, out in (rd or {}).items():
            if m != "_meta" and isinstance(out, str):
                combined[f"r{i}:{m}"] = out
    if synthesis:
        combined["synthesis"] = synthesis
    try:
        phantoms = swarm_filestore.verify_round_claims(combined).get("phantoms") or []
        return sorted({p["path"] for p in phantoms})
    except Exception as e:  # never let telemetry break the closer
        logger.warning(f"[closer] phantom-claim check failed: {type(e).__name__}: {e}")
        return None  # unknown, not zero


def find_honest_verb_violations(all_rounds: list[dict], synthesis: str,
                                phantom_paths: "list[str] | None") -> "list[str] | None":
    """The phantom paths that were asserted with STRONG completion language
    ("written and verified", "read back", "byte matches") — active deception, a
    strict subset of persistence_gap.

    Existence is the gate (phantom_paths); completion cues only sort severity, so
    a phantom bare-mentioned is NOT a violation while the same phantom claimed
    complete IS. Returns None when phantom detection itself was unavailable (so
    the scorecard reports unknown, never a false 0), else the sorted subset.
    """
    if phantom_paths is None:
        return None
    if not phantom_paths:
        return []
    import swarm_filestore
    phantom_set = set(phantom_paths)
    violations: set[str] = set()
    try:
        for i, rd in enumerate(all_rounds or []):
            for m, out in (rd or {}).items():
                if m == "_meta" or not isinstance(out, str):
                    continue
                for path in swarm_filestore.detect_completion_claims(out):
                    if path in phantom_set:
                        violations.add(path)
        if synthesis:
            for path in swarm_filestore.detect_completion_claims(synthesis):
                if path in phantom_set:
                    violations.add(path)
        return sorted(violations)
    except Exception as e:
        logger.warning(f"[closer] honest-verb check failed: {type(e).__name__}: {e}")
        return None


def build_scorecard(digest: dict, *, phantom_paths: "list[str] | None",
                    honest_verb_violations: "list[str] | None" = None) -> dict:
    """Pure function: map a closer digest + verified phantom paths to the v0
    scorecard.

    Everything here is an objective counter derived from what actually happened.
    `phantom_paths` is the claimed-vs-found diff from find_phantom_claims — its
    length is persistence_gap, and the paths themselves are recorded so the gap
    is actionable (which claims went unpersisted), not just a magnitude.

    If `phantom_paths` is None the detector failed to run: the scorecard reports
    the gap as UNKNOWN (null + status "unavailable"), never as 0 — 0 would
    falsely certify "we checked and found none". Fields that need deeper
    plumbing (cost, structured tool-call counts, citations) are likewise emitted
    as null with a reason rather than guessed.
    """
    rounds = digest.get("rounds") or []
    models_active = sorted({m for r in rounds for m in (r.get("models") or [])})
    measured = phantom_paths is not None
    pp = list(phantom_paths) if measured else []
    gap = len(pp) if measured else None
    # Honest-verb violations: phantoms asserted with strong completion language.
    # Existence gates; cues sort severity. null (not 0) when unmeasured.
    hv_measured = honest_verb_violations is not None
    hv = list(honest_verb_violations) if hv_measured else []
    hv_count = len(hv) if hv_measured else None
    return {
        "scorecard_version": SCORECARD_VERSION,
        "session_id": digest.get("session_id"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "query": (digest.get("query") or "")[:200],
        "rounds": len(rounds),
        "models_active": models_active,
        "duration_sec": digest.get("duration_sec"),
        "filestore": {
            "writes": len(digest.get("fs_writes") or []),
            "appends": len(digest.get("fs_appends") or []),
            "rejected": len(digest.get("fs_rejected") or []),
            # null (not 0) when the detector couldn't run — see status below.
            "phantom_write_claims": gap,
            "phantom_write_claims_status": "ok" if measured else "unavailable",
            # The named diff — verify-then-emit made visible (capped for size).
            "phantom_paths": pp[:20],
            # Of those phantoms, how many were asserted with strong completion
            # language ("written and verified", "read back") — active deception,
            # a strict subset of the gap. Existence gates; cues only sort here.
            # null when unmeasured; NOT a self-graded severity, just a count.
            "honest_verb_violations": hv_count,
            "honest_verb_violation_paths": hv[:20],
        },
        # persistence_gap v0 == distinct claimed-but-unpersisted writes: the exact
        # failure mode the swarm demonstrated while discussing phantom artifacts.
        # null when unmeasured — "unknown" is not the same as "none".
        "persistence_gap": gap,
        "mail": {
            "sent": len(digest.get("mail_sent") or []),
            "rejected": len(digest.get("mail_rejected") or []),
        },
        "synthesis_directives": {
            "blockers": len(digest.get("blockers") or []),
            "reviews": len(digest.get("reviews") or []),
            "flags": len(digest.get("flags") or []),
        },
        "truncated_models": digest.get("truncated_models") or [],
        "rate_limited_models": digest.get("rate_limited_models") or [],
        "audit_counts": digest.get("audit_counts"),
        # Deferred — emitted null so consumers see the field exists but isn't
        # populated yet, rather than silently missing.
        "cost_usd": None,
        "tool_calls": None,
        "citations_claimed": None,
        "citations_verified": None,
        "deferred_fields": {
            "cost_usd": "needs API-billing plumbing from the loop engine",
            "tool_calls": "needs structured tool-call counts from the loop engine",
            "citations_claimed/verified": "needs citation extraction",
            "quality/usefulness scores": "excluded by design — require an independent grader, not self-report",
        },
    }


def _path_of(item) -> str:
    if isinstance(item, dict):
        return item.get("path") or item.get("file") or str(item)
    return str(item)


def format_digest_email(digest: dict) -> tuple[str, str]:
    """Returns (subject, body). Plain text + markdown formatting."""
    counts = digest.get("audit_counts")
    gap = counts["gap"] if counts else None

    if gap is not None and gap > 0:
        subject_tail = f"gap={gap}"
    elif digest.get("blockers"):
        subject_tail = f"{len(digest['blockers'])} blocker(s)"
    elif digest.get("truncated_models") or digest.get("rate_limited_models"):
        subject_tail = "model issues"
    else:
        subject_tail = "clean"

    subject = f"Swarm Closer — Session {digest['session_id']} — {subject_tail}"

    lines: list[str] = []

    q = digest["query"]
    if q:
        q_short = q.replace("\n", " ").strip()
        if len(q_short) > 200:
            q_short = q_short[:197] + "..."
        lines.append(f"**Query:** {q_short}")
        lines.append("")

    # 1. What needs you
    lines.append("## What needs you")
    needs: list[str] = []
    for d in digest["blockers"]:
        needs.append(f"- [BLOCKER] {d['subject']}")
    for d in digest["reviews"]:
        needs.append(f"- [REVIEW] {d['subject']}")
    if not needs:
        needs.append("- (nothing flagged for your attention)")
    lines.extend(needs)
    lines.append("")

    # 2. What moved
    lines.append("## What moved")
    moved: list[str] = []
    if digest["fs_writes"]:
        moved.append(f"- {len(digest['fs_writes'])} file(s) written from synthesis:")
        for w in digest["fs_writes"][:10]:
            moved.append(f"  - `{_path_of(w)}`")
        if len(digest["fs_writes"]) > 10:
            moved.append(f"  - ...and {len(digest['fs_writes']) - 10} more")
    if digest["fs_appends"]:
        moved.append(f"- {len(digest['fs_appends'])} file(s) appended from synthesis:")
        for a in digest["fs_appends"][:10]:
            moved.append(f"  - `{_path_of(a)}`")
    if digest["mail_sent"]:
        moved.append(f"- {len(digest['mail_sent'])} email(s) sent from synthesis:")
        for e in digest["mail_sent"]:
            moved.append(f"  - {e.get('subject', '?')} (from {e.get('model', '?')})")
    if digest["flags"]:
        moved.append(f"- {len(digest['flags'])} [FLAG] item(s) noted in synthesis")
    if not moved:
        moved.append("- (no filestore or mail activity from synthesis)")
    lines.extend(moved)
    lines.append("")

    # 3. What's owed
    lines.append("## What's owed")
    owed: list[str] = []
    if counts:
        owed.append(
            f"- Audit: triggers_identified={counts['triggers_identified']}, "
            f"emails_sent={counts['emails_sent']}, gap={counts['gap']}"
        )
        if counts["gap"] > 0:
            owed.append(f"  - **{counts['gap']} email trigger(s) identified but not sent**")
    else:
        owed.append("- (no audit COUNTS block found in synthesis section 6)")
    # Carry the substance, not just the count: when the swarm flagged things but
    # didn't email them (gap > 0, or no audit block at all), list what they were
    # so the info reaches the Conductor regardless of the directive dance.
    trigger_items = digest.get("trigger_items") or []
    if trigger_items and (gap is None or gap > 0):
        owed.append("- What was flagged (so you have it even if no email fired):")
        for it in trigger_items:
            owed.append(f"  - [{it['tier']}] {it['text']}")
    if digest["mail_rejected"]:
        owed.append(f"- {len(digest['mail_rejected'])} email(s) rejected from synthesis:")
        for e in digest["mail_rejected"]:
            owed.append(f"  - {e.get('subject', '?')} — {e.get('reason', '?')}")
    if digest["fs_rejected"]:
        owed.append(f"- {len(digest['fs_rejected'])} filestore write(s) rejected from synthesis")
    lines.extend(owed)
    lines.append("")

    # 4. Round-by-round (collapsed)
    lines.append("## Round-by-round")
    for r in digest["rounds"]:
        models_str = ", ".join(r["models"]) if r["models"] else "(no models)"
        lines.append(f"- Round {r['round']}: {models_str}")
    if digest.get("duration_sec"):
        lines.append(f"- Total duration: {digest['duration_sec']}s")
    lines.append("")

    # 5. Truncations & rate limits
    if digest["truncated_models"] or digest["rate_limited_models"]:
        lines.append("## Truncations & rate limits")
        if digest["truncated_models"]:
            lines.append(f"- Tool-loop truncations: {', '.join(digest['truncated_models'])}")
        if digest["rate_limited_models"]:
            lines.append(f"- Rate-limit indicators (429-class): {', '.join(digest['rate_limited_models'])}")
        lines.append("")

    return subject, "\n".join(lines).strip()


def _marker_path(session_id: str, outputs_dir: Path) -> Path:
    return outputs_dir / f"{session_id}.closer-fired.json"


def _send_via_smtp(subject: str, body: str, session_id: str) -> tuple[bool, str]:
    """Send the digest via smtplib directly. Bypasses swarm_mail's per-session
    rate limit because the Closer is a system-level send, not a model-emitted
    directive. Still respects SMTP env config. Returns (success, reason)."""
    needed = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_APP_PASSWORD", "RRI_CONDUCTOR_EMAIL"]
    missing = [v for v in needed if not os.getenv(v)]
    if missing:
        return False, f"missing env vars: {', '.join(missing)}"

    to_addr = os.getenv("RRI_CONDUCTOR_EMAIL")
    from_addr = os.getenv("SMTP_USER")
    full_subject = f"[RRI Closer] {subject.strip()[:140]}"
    full_body = (
        f"{body}\n\n"
        f"---\n"
        f"Session: {session_id}\n"
        f"Sent: {datetime.now().isoformat(timespec='seconds')}\n"
    )

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = full_subject
    msg.attach(MIMEText(full_body, "plain"))

    try:
        host = os.getenv("SMTP_HOST")
        port = int(os.getenv("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(from_addr, os.getenv("SMTP_APP_PASSWORD"))
            server.sendmail(from_addr, to_addr, msg.as_string())
        return True, "sent"
    except smtplib.SMTPException as e:
        return False, f"smtp error: {e}"
    except (OSError, ValueError) as e:
        return False, f"send error: {e}"


def run_post_session_closer(
    *,
    query: str,
    all_rounds: list[dict],
    synthesis: str,
    session_id: str,
    outputs_dir: Path,
    logs_dir: Path,
    fs_synth: Optional[dict] = None,
    mail_synth: Optional[dict] = None,
    duration: Optional[float] = None,
) -> None:
    """Top-level entrypoint. Fires on a daemon thread so SMTP latency never
    blocks session completion. Idempotent via marker file. Failures are
    logged but never raised."""
    if not _enabled():
        logger.info(f"[closer] disabled via RRI_CLOSER_ENABLED; skipping session {session_id}")
        return

    def _worker():
        marker = _marker_path(session_id, outputs_dir)
        try:
            if marker.exists():
                logger.info(f"[closer] marker exists for session {session_id}; skipping")
                return

            digest = build_digest(
                query=query,
                all_rounds=all_rounds,
                synthesis=synthesis,
                session_id=session_id,
                fs_synth=fs_synth,
                mail_synth=mail_synth,
                duration=duration,
            )
            subject, body = format_digest_email(digest)

            logs_dir.mkdir(parents=True, exist_ok=True)
            local_path = logs_dir / f"closer-digest-{session_id}.md"
            local_path.write_text(f"# {subject}\n\n{body}\n")

            # Session scorecard (mechanical counters). Fail-loud: a scorecard
            # write failure is logged but never aborts the closer or the session.
            try:
                phantom_paths = find_phantom_claims(all_rounds, synthesis)
                honest_verb_violations = find_honest_verb_violations(all_rounds, synthesis, phantom_paths)
                scorecard = build_scorecard(digest, phantom_paths=phantom_paths,
                                            honest_verb_violations=honest_verb_violations)
                scorecard_path = logs_dir / f"scorecard-{session_id}.json"
                # Atomic write (temp + os.replace), same discipline as the
                # dispatch queue — a crash mid-write can't leave a torn scorecard.
                tmp = scorecard_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(scorecard, indent=2))
                os.replace(tmp, scorecard_path)
                gap = scorecard["persistence_gap"]
                logger.info(
                    f"[closer] scorecard written: {scorecard_path} "
                    f"(rounds={scorecard['rounds']}, persistence_gap="
                    f"{gap if gap is not None else 'unknown'})"
                )
                if phantom_paths:  # None (unknown) is falsy but has no paths to name
                    logger.warning(f"[closer] phantom write claims (unpersisted): {phantom_paths}")
            except Exception as e:
                logger.error(f"[closer] scorecard emit failed for session {session_id}: "
                             f"{type(e).__name__}: {e}")

            sent, reason = _send_via_smtp(subject, body, session_id)
            outcome = "emailed" if sent else f"logged-only ({reason})"

            outputs_dir.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({
                "session_id": session_id,
                "fired_at": datetime.now().isoformat(timespec="seconds"),
                "outcome": outcome,
                "local_path": str(local_path),
                "subject": subject,
            }, indent=2))

            logger.info(f"[closer] session {session_id}: {outcome}; digest at {local_path}")
        except Exception as e:
            logger.error(f"[closer] failed for session {session_id}: {type(e).__name__}: {e}")

    threading.Thread(target=_worker, daemon=True, name=f"closer-{session_id}").start()


def status() -> dict:
    return {
        "enabled": _enabled(),
        "version": 1,
        "scorecard_version": SCORECARD_VERSION,
    }
