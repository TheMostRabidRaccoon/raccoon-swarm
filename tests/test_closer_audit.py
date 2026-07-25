"""Closer ground-truth accounting: rate-limit attribution + email reconciliation.

Regression tests for two Session 141/142 audit defects:

1. Rate limits were detected by grepping model PROSE for "429"-style strings,
   so Grok merely mentioning GPT's quota failure convicted Grok (and one bad
   round convicted all five seats). Only a model whose own call failed — its
   entire output is an "[<Label> error: ...]" marker — may be flagged.

2. emails_sent was taken from the model's self-graded audit block, which
   counted [EMAIL_CONDUCTOR] intentions as sends (claimed 4, actual 0).
   The mail log (emails.log) is the ground truth and covers round-level
   sends that mail_synth (synthesis-stage only) never sees.
"""
import swarm_closer as closer
import swarm_filestore as fs

SYNTH_CLAIMING_4 = "6. COUNTS\ntriggers_identified: 4\nemails_sent: 4\ngap: 0"


def _log_send(model: str, session: str, subject: str = "s") -> None:
    fs.ensure_layout()
    fs.append_file(
        "/logs/emails.log",
        f"2026-07-13T20:14:46.000000 | model={model} | session={session}\n"
        f"subject: {subject}\n"
        f"body: b\n",
    )


# ── rate-limit attribution ──────────────────────────────────────────────


def test_prose_mention_of_429_does_not_convict(storage):
    rounds = [{
        "grok": "GPT failed with a 429 insufficient_quota earlier; covering its beat.",
        "claude": "Discussing rate limit strategy in the abstract. TooManyRequests.",
    }]
    d = closer.build_digest(query="q", all_rounds=rounds, synthesis="",
                            session_id="s141")
    assert d["rate_limited_models"] == []


def test_actual_error_marker_convicts_only_failing_model(storage):
    rounds = [{
        "gpt": "[GPT error: Error code: 429 - insufficient_quota]",
        "grok": "Noting that GPT hit a 429 again. My own call is fine.",
    }]
    d = closer.build_digest(query="q", all_rounds=rounds, synthesis="",
                            session_id="s142")
    assert d["rate_limited_models"] == ["gpt"]


def test_non_ratelimit_error_marker_not_flagged(storage):
    rounds = [{"gemini": "[Gemini error: connection reset by peer]"}]
    d = closer.build_digest(query="q", all_rounds=rounds, synthesis="",
                            session_id="s1")
    assert d["rate_limited_models"] == []


# ── email reconciliation ────────────────────────────────────────────────


def test_claimed_sends_overridden_by_email_log(storage):
    _log_send("claude", "s142")                    # 1 real send this session
    _log_send("operational", "s142")               # gazette: never counts
    _log_send("claude", "other-session")           # different session

    d = closer.build_digest(query="q", all_rounds=[{"claude": "ok"}],
                            synthesis=SYNTH_CLAIMING_4, session_id="s142",
                            mail_synth={"sent": [], "rejected": []})
    c = d["audit_counts"]
    assert c["emails_sent"] == 1
    assert c["emails_sent_claimed"] == 4
    assert c["gap"] == 3
    assert "claimed 4" in c["discrepancy"]


def test_round_level_sends_are_counted(storage):
    """mail_synth only sees synthesis-stage sends; the log sees all stages."""
    _log_send("gemini", "s143")  # round-level send, absent from mail_synth
    synth = "6. COUNTS\ntriggers_identified: 1\nemails_sent: 1\ngap: 0"

    d = closer.build_digest(query="q", all_rounds=[{"gemini": "ok"}],
                            synthesis=synth, session_id="s143",
                            mail_synth={"sent": [], "rejected": []})
    c = d["audit_counts"]
    assert c["emails_sent"] == 1
    assert "discrepancy" not in c


def test_missing_log_falls_back_to_mail_synth(storage):
    """An unreadable log is 'unknown', not zero — fall back to mail_synth."""
    sent = [{"model": "claude", "subject": "x"}]
    d = closer.build_digest(query="q", all_rounds=[{"claude": "ok"}],
                            synthesis=SYNTH_CLAIMING_4, session_id="s144",
                            mail_synth={"sent": sent, "rejected": []})
    c = d["audit_counts"]
    assert c["emails_sent"] == 1
    assert c["gap"] == 3


def test_agreeing_counts_carry_no_discrepancy(storage):
    _log_send("claude", "s145")
    synth = "6. COUNTS\ntriggers_identified: 2\nemails_sent: 1\ngap: 1"
    d = closer.build_digest(query="q", all_rounds=[{"claude": "ok"}],
                            synthesis=synth, session_id="s145",
                            mail_synth={"sent": [], "rejected": []})
    c = d["audit_counts"]
    assert c["emails_sent"] == 1
    assert "discrepancy" not in c
