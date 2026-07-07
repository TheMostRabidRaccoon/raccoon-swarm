"""Gazette layer tests — collectors read receipts, editions render honestly,
and the attachment invariant refuses to send what doesn't exist.

Stdlib-only (CI has no python-docx / SMTP): the DOCX path is exercised only
for its honest-False fallback unless python-docx happens to be installed, and
the mail tests target the pure _prepare_attachments helper, never a socket.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import swarm_gazette
import swarm_mail


# ---- PLAY classification ---------------------------------------------------

def test_purpose_tag_wins():
    assert swarm_gazette.is_play_session("[SESSION_PURPOSE: creative-production] assemble act 3")


def test_play_markers_detected():
    assert swarm_gazette.is_play_session("SESSION OPEN — THE BOUNCER S01E03 table read")
    assert swarm_gazette.is_play_session("Woodland Council freeplay. Pure foo-foo.")
    assert not swarm_gazette.is_play_session("Meta-evaluate the repo. Be brutal.")


def test_empty_query_is_not_play():
    assert not swarm_gazette.is_play_session("")


# ---- collectors -------------------------------------------------------------

def _write_receipts(logs_dir: Path, sid: str, *, query="fix the bugs", gap=0,
                    blockers=0, flags=1, truncated=None, audit_gap=None):
    logs_dir.mkdir(parents=True, exist_ok=True)
    scorecard = {
        "session_id": sid,
        "query": query,
        "rounds": 3,
        "models_active": ["claude", "gpt"],
        "persistence_gap": gap,
        "filestore": {"phantom_paths": [], "honest_verb_violations": 0},
        "synthesis_directives": {"blockers": blockers, "reviews": 0, "flags": flags},
        "truncated_models": truncated or [],
        "rate_limited_models": [],
        "audit_counts": {"gap": audit_gap} if audit_gap is not None else None,
    }
    (logs_dir / f"scorecard-{sid}.json").write_text(json.dumps(scorecard))
    (logs_dir / f"closer-digest-{sid}.md").write_text(
        "# subject\n\n## What needs you\n- [BLOCKER] ratify the severity table\n\n## What moved\n- stuff\n")


def test_collect_sessions_window_is_by_session_id_timestamp(tmp_path):
    _write_receipts(tmp_path, "20260704_120000")
    _write_receipts(tmp_path, "20260701_120000")  # outside window
    since = datetime(2026, 7, 3)
    got = swarm_gazette.collect_sessions(tmp_path, since, datetime(2026, 7, 5))
    assert [s["session_id"] for s in got] == ["20260704_120000"]
    assert got[0]["needs_you"] == ["[BLOCKER] ratify the severity table"]


def test_collect_sessions_tolerates_torn_scorecard(tmp_path):
    (tmp_path / "scorecard-20260704_120000.json").write_text("{not json")
    got = swarm_gazette.collect_sessions(tmp_path, datetime(2026, 7, 3), datetime(2026, 7, 5))
    assert len(got) == 1  # the session is listed, its fields unmeasured
    assert got[0]["rounds"] is None


def test_collect_email_log_parses_window(storage):
    import swarm_filestore
    swarm_filestore.append_file("/logs/emails.log",
        "2026-07-04T10:00:00 | model=claude | session=x\nsubject: [RRI Swarm] hello\nbody: hi\n")
    swarm_filestore.append_file("/logs/emails.log",
        "2026-06-01T10:00:00 | model=gpt | session=y\nsubject: [RRI Swarm] old\nbody: hi\n")
    got = swarm_gazette.collect_email_log(datetime(2026, 7, 1), datetime(2026, 7, 5))
    assert [e["subject"] for e in got] == ["[RRI Swarm] hello"]


# ---- Daily Burrow -----------------------------------------------------------

def test_burrow_subject_counts_and_gap_surfacing(tmp_path):
    _write_receipts(tmp_path, "20260704_120000", blockers=1, audit_gap=2)
    sessions = swarm_gazette.collect_sessions(tmp_path, datetime(2026, 7, 3), datetime(2026, 7, 5))
    subject, body = swarm_gazette.build_daily_burrow(
        date_str="2026-07-04", sessions=sessions, joy_runs=[], email_entries=[])
    assert "1 session(s)" in subject and "1 blocker(s)" in subject
    assert "2 unsent email(s)" in subject
    # The gap is repeated verbatim in the body with a pointer to the digest.
    assert "gap=2" in body and "closer-digest-20260704_120000.md" in body


def test_burrow_quiet_day_is_honest():
    subject, body = swarm_gazette.build_daily_burrow(
        date_str="2026-07-07", sessions=[], joy_runs=[], email_entries=[])
    assert "0 session(s)" in subject
    assert "quiet burrow" in body.lower()


def test_burrow_unmeasured_renders_as_question_mark(tmp_path):
    (tmp_path / "scorecard-20260704_120000.json").write_text("{not json")
    sessions = swarm_gazette.collect_sessions(tmp_path, datetime(2026, 7, 3), datetime(2026, 7, 5))
    _, body = swarm_gazette.build_daily_burrow(
        date_str="2026-07-04", sessions=sessions, joy_runs=[], email_entries=[])
    assert "| 20260704_120000 | ? |" in body  # unmeasured != 0


# ---- Play Gazette -----------------------------------------------------------

def test_play_gazette_marks_clipped_sessions(tmp_path):
    _write_receipts(tmp_path, "20260701_225850",
                    query="SESSION OPEN — THE BOUNCER S01E03", truncated=["claude"])
    session = swarm_gazette.collect_sessions(tmp_path, datetime(2026, 7, 1), datetime(2026, 7, 2))[0]
    subject, body = swarm_gazette.build_play_gazette(session)
    assert "CLIPPED" in subject
    assert "INCOMPLETE / CLIPPED" in body
    assert "claude" in body  # names the clipped seat


def test_play_gazette_complete_session(tmp_path):
    _write_receipts(tmp_path, "20260703_164805", query="Joy Mode council vote")
    session = swarm_gazette.collect_sessions(tmp_path, datetime(2026, 7, 3), datetime(2026, 7, 4))[0]
    subject, body = swarm_gazette.build_play_gazette(session)
    assert "CLIPPED" not in subject
    assert "**complete**" in body


def test_fire_play_gazette_is_idempotent(storage, tmp_path, monkeypatch):
    import swarm_filestore
    logs = tmp_path / "logs"
    _write_receipts(logs, "20260701_225850", query="THE BOUNCER table read")
    # Publishing requires no SMTP: force send_operational to record calls.
    calls = []
    monkeypatch.setattr(swarm_mail, "send_operational",
                        lambda *a, **k: (calls.append(k) or (True, "sent")))
    first = swarm_gazette.fire_play_gazette(
        session_id="20260701_225850", logs_dir=logs, outputs_dir=tmp_path / "out")
    assert first["published"] is True
    assert swarm_filestore.read_file(swarm_gazette.play_gazette_path("20260701_225850"))
    second = swarm_gazette.fire_play_gazette(
        session_id="20260701_225850", logs_dir=logs, outputs_dir=tmp_path / "out")
    assert second["published"] is False  # edition already on disk
    assert len(calls) == 1


def test_fire_play_gazette_without_receipts_publishes_nothing(storage, tmp_path):
    got = swarm_gazette.fire_play_gazette(
        session_id="20260701_225850", logs_dir=tmp_path / "empty", outputs_dir=tmp_path / "out")
    assert got == {"session_id": "20260701_225850", "published": False,
                   "emailed": False, "docx": None}


# ---- DOCX honesty -----------------------------------------------------------

def test_render_docx_never_raises(tmp_path):
    # With python-docx installed this renders; without it, it returns False.
    # Either way the caller can trust the boolean and never claims a phantom
    # attachment.
    ok = swarm_gazette.render_docx("t", "# T\n\n## S\n- a\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
                                   tmp_path / "t.docx")
    assert ok is (tmp_path / "t.docx").exists()


# ---- attachment invariant ---------------------------------------------------

def test_prepare_attachments_hashes_real_files(tmp_path):
    f = tmp_path / "gazette.docx"
    f.write_bytes(b"raccoon newspaper")
    records, reason = swarm_mail._prepare_attachments([str(f)])
    assert reason == "ok"
    assert records[0]["name"] == "gazette.docx"
    assert records[0]["size"] == len(b"raccoon newspaper")
    assert len(records[0]["sha256"]) == 64


def test_prepare_attachments_refuses_missing_file(tmp_path):
    records, reason = swarm_mail._prepare_attachments([str(tmp_path / "ghost.docx")])
    assert records is None
    assert "ghost.docx" in reason  # the refusal names the phantom


def test_send_operational_aborts_on_missing_attachment(tmp_path, monkeypatch):
    # Config present, attachment absent: the send must abort BEFORE SMTP —
    # "I attached the newspaper" may never outrun the newspaper.
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_APP_PASSWORD", "RRI_CONDUCTOR_EMAIL"):
        monkeypatch.setenv(var, "587" if var == "SMTP_PORT" else "x")
    import smtplib
    def _boom(*a, **k):
        raise AssertionError("SMTP must not be reached for a phantom attachment")
    monkeypatch.setattr(smtplib, "SMTP", _boom)
    ok, reason = swarm_mail.send_operational(
        "s", "b", attachments=[str(tmp_path / "ghost.docx")])
    assert ok is False
    assert "attachment missing" in reason
