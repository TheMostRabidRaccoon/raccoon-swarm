"""Swarm mail — the swarm can email the Conductor (only) when something
genuinely needs human attention.

Hard constraints baked in:
- Recipient is locked to RRI_CONDUCTOR_EMAIL env var. Models cannot redirect.
- Rate-limited: max 6 per session, max 10 per rolling 24h.
- Every send is appended to /swarm/logs/emails.log via swarm_filestore.
- Subject auto-prefixed with [RRI Swarm].
- Body auto-appended with model + session_id + timestamp.

Directive syntax models emit:
  [EMAIL_CONDUCTOR: subject text here]
  body markdown here
  [/EMAIL_CONDUCTOR]
"""
from __future__ import annotations

import os
import re
import smtplib
import logging
import threading
from collections import deque
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import swarm_filestore

logger = logging.getLogger("SwarmVault")

MAX_PER_SESSION = 6
MAX_PER_24H = 10

_session_counts: dict[str, int] = {}
_recent_sends: deque[datetime] = deque()
_lock = threading.Lock()


# ============================================================
# Config + rate limiting
# ============================================================

def _config_status() -> tuple[bool, str]:
    needed = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_APP_PASSWORD", "RRI_CONDUCTOR_EMAIL"]
    missing = [v for v in needed if not os.getenv(v)]
    if missing:
        return False, f"missing env vars: {', '.join(missing)}"
    return True, "ok"


def _check_rate_limits(session_id: str) -> tuple[bool, str]:
    with _lock:
        if _session_counts.get(session_id, 0) >= MAX_PER_SESSION:
            return False, f"session limit ({MAX_PER_SESSION}) reached"
        cutoff = datetime.now() - timedelta(hours=24)
        while _recent_sends and _recent_sends[0] < cutoff:
            _recent_sends.popleft()
        if len(_recent_sends) >= MAX_PER_24H:
            return False, f"daily limit ({MAX_PER_24H}) reached"
    return True, "ok"


def _record_send(session_id: str) -> None:
    with _lock:
        _session_counts[session_id] = _session_counts.get(session_id, 0) + 1
        _recent_sends.append(datetime.now())


# ============================================================
# Send
# ============================================================

def send_to_conductor(subject: str, body: str, model: str, session_id: str = "unknown") -> tuple[bool, str]:
    """Send an email to the Conductor. Returns (success, reason)."""
    ok, reason = _config_status()
    if not ok:
        return False, reason

    allowed, reason = _check_rate_limits(session_id)
    if not allowed:
        return False, reason

    to_addr = os.getenv("RRI_CONDUCTOR_EMAIL")
    from_addr = os.getenv("SMTP_USER")

    full_subject = f"[RRI Swarm] {subject.strip()[:120]}"
    full_body = (
        f"{body.strip()}\n\n"
        f"---\n"
        f"From: {model}\n"
        f"Session: {session_id}\n"
        f"Sent: {datetime.now().isoformat(timespec='seconds')}\n"
        f"\n"
        f"Inspect via /memory or /filestore on the swarm server.\n"
    )

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = full_subject
    msg.attach(MIMEText(full_body, "plain"))

    try:
        host = os.getenv("SMTP_HOST")
        port = int(os.getenv("SMTP_PORT", "587"))
        password = os.getenv("SMTP_APP_PASSWORD")
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(from_addr, password)
            server.sendmail(from_addr, to_addr, msg.as_string())
    except smtplib.SMTPException as e:
        logger.error(f"swarm_mail SMTP error: {e}")
        return False, f"smtp error: {e}"
    except (OSError, ValueError) as e:
        logger.error(f"swarm_mail send failed: {e}")
        return False, f"send error: {e}"

    _record_send(session_id)

    log_entry = (
        f"{datetime.now().isoformat()} | model={model} | session={session_id}\n"
        f"subject: {full_subject}\n"
        f"body: {body[:500]}{'...' if len(body) > 500 else ''}\n"
    )
    try:
        swarm_filestore.append_file("/logs/emails.log", log_entry)
    except Exception as e:  # never let audit-log failure block the send
        logger.error(f"swarm_mail audit-log failed (send still succeeded): {e}")

    logger.info(f"swarm_mail sent to conductor — model={model} subject={full_subject!r}")
    return True, "sent"


# ============================================================
# Operational channel — system sends (gazettes), not model directives
# ============================================================

def _prepare_attachments(paths: "list[str] | None") -> tuple["list[dict] | None", str]:
    """Verify and hash every attachment BEFORE any send. Returns
    ([{path, name, sha256, size}], "ok") or (None, reason).

    Fail-closed on purpose: a missing attachment aborts the whole send rather
    than mailing an email that claims a file it doesn't carry — the attachment
    version of "announcing a write is not a write"."""
    import hashlib
    records: list[dict] = []
    for p in paths or []:
        path = Path(p)
        try:
            data = path.read_bytes()
        except OSError as e:
            return None, f"attachment missing/unreadable: {p} ({e})"
        records.append({
            "path": str(path),
            "name": path.name,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "_data": data,
        })
    return records, "ok"


def send_operational(subject: str, body: str, *, attachments: "list[str] | None" = None,
                     prefix: str = "[RRI Swarm]", session_id: str = "operational") -> tuple[bool, str]:
    """Send a system-level email to the Conductor (gazettes, daemon digests).

    This is NOT reachable from model output — the directive parser only routes
    [EMAIL_CONDUCTOR] blocks to send_to_conductor. The recipient stays locked
    to RRI_CONDUCTOR_EMAIL. Like the closer's digest sends, this bypasses the
    per-session/24h model rate caps: it runs on a fixed systemd cadence, so a
    busy swarm day must not starve the Conductor's own newspaper.

    Attachment invariant: every attachment must exist and is sha256-hashed
    before the send; any missing file aborts the send entirely, and the
    emails.log entry records each attachment's name + hash + the send status.
    """
    ok, reason = _config_status()
    if not ok:
        return False, reason

    records, reason = _prepare_attachments(attachments)
    if records is None:
        logger.error(f"swarm_mail operational send refused: {reason}")
        return False, reason

    to_addr = os.getenv("RRI_CONDUCTOR_EMAIL")
    from_addr = os.getenv("SMTP_USER")
    full_subject = f"{prefix} {subject.strip()[:120]}"

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = full_subject
    msg.attach(MIMEText(body, "plain"))
    for rec in records:
        part = MIMEApplication(rec["_data"], Name=rec["name"])
        part["Content-Disposition"] = f'attachment; filename="{rec["name"]}"'
        msg.attach(part)

    try:
        host = os.getenv("SMTP_HOST")
        port = int(os.getenv("SMTP_PORT", "587"))
        password = os.getenv("SMTP_APP_PASSWORD")
        with smtplib.SMTP(host, port, timeout=60) as server:
            server.starttls()
            server.login(from_addr, password)
            server.sendmail(from_addr, to_addr, msg.as_string())
    except smtplib.SMTPException as e:
        logger.error(f"swarm_mail operational SMTP error: {e}")
        return False, f"smtp error: {e}"
    except (OSError, ValueError) as e:
        logger.error(f"swarm_mail operational send failed: {e}")
        return False, f"send error: {e}"

    attach_lines = "".join(
        f"attachment: {r['name']} sha256={r['sha256']} size={r['size']}\n" for r in records)
    log_entry = (
        f"{datetime.now().isoformat()} | model=operational | session={session_id}\n"
        f"subject: {full_subject}\n"
        f"{attach_lines}"
        f"status: sent\n"
        f"body: {body[:500]}{'...' if len(body) > 500 else ''}\n"
    )
    try:
        swarm_filestore.append_file("/logs/emails.log", log_entry)
    except Exception as e:  # never let audit-log failure block the send
        logger.error(f"swarm_mail audit-log failed (send still succeeded): {e}")

    logger.info(f"swarm_mail operational sent — subject={full_subject!r} "
                f"attachments={len(records)}")
    return True, "sent"


# ============================================================
# Directive parsing
# ============================================================

_EMAIL_RE = re.compile(
    r"\[EMAIL_CONDUCTOR:\s*([^\]]+)\]\s*\n?(.*?)\n?\[/EMAIL_CONDUCTOR\]",
    re.DOTALL,
)


def parse_email_directives(text: str) -> list[tuple[str, str]]:
    if not text:
        return []
    return [(m.group(1).strip(), m.group(2).strip()) for m in _EMAIL_RE.finditer(text)]


def process_round_emails(round_results: dict, session_id: str) -> dict:
    """Walk a round's outputs, send any [EMAIL_CONDUCTOR] directives."""
    summary = {"sent": [], "rejected": []}
    for model_name, output in round_results.items():
        if model_name == "_meta" or not isinstance(output, str):
            continue
        for subject, body in parse_email_directives(output):
            ok, reason = send_to_conductor(subject, body, model_name, session_id)
            entry = {"model": model_name, "subject": subject, "reason": reason}
            (summary["sent"] if ok else summary["rejected"]).append(entry)
    return summary


# ============================================================
# Diagnostics
# ============================================================

def status() -> dict:
    """Snapshot of mail config + rate-limit state for /mail/status endpoint."""
    ok, reason = _config_status()
    cutoff = datetime.now() - timedelta(hours=24)
    with _lock:
        recent_count = sum(1 for t in _recent_sends if t >= cutoff)
        per_session = dict(_session_counts)
    return {
        "configured": ok,
        "config_status": reason,
        "max_per_session": MAX_PER_SESSION,
        "max_per_24h": MAX_PER_24H,
        "sent_in_last_24h": recent_count,
        "per_session_counts": per_session,
        "conductor_email_set": bool(os.getenv("RRI_CONDUCTOR_EMAIL")),
    }
