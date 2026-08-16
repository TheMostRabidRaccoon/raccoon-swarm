"""Notification policy for the mechanical session closer.

The closer's telemetry is useful even when nobody needs to be interrupted. This
module separates MEASUREMENT from NOTIFICATION:

- scorecards/digests/corpus receipts may still be produced every session;
- routine clean sessions are quiet by default;
- meaningful blockers/reviews/flags/gaps/model issues may notify;
- `RRI_CLOSER_NOTIFY_MODE=all|signal|off` controls interruption policy.

This is deliberately a notification policy, not a productivity criterion.
"""
from __future__ import annotations

import os


VALID_MODES = {"all", "signal", "off"}


def notify_mode() -> str:
    mode = (os.getenv("RRI_CLOSER_NOTIFY_MODE") or "signal").strip().lower()
    return mode if mode in VALID_MODES else "signal"


def has_signal(subject: str, body: str) -> bool:
    """Whether a closer digest contains something that plausibly merits interruption."""
    s = (subject or "").lower()
    b = (body or "").lower()

    # Non-clean subject states are generated for audit gaps, blockers, truncations,
    # rate limits, etc. Keep the body checks too because some FLAG-only digests can
    # otherwise retain a "clean" subject in the legacy formatter.
    if not s.endswith("— clean") and not s.endswith("- clean"):
        return True

    cues = (
        "[blocker]",
        "[review]",
        "[flag]",
        "audit miscount",
        "email trigger(s) identified but not sent",
        "truncations & rate limits",
        "rate-limit indicators",
        "tool-loop truncations",
    )
    return any(cue in b for cue in cues)


def should_notify(subject: str, body: str, mode: str | None = None) -> bool:
    mode = (mode or notify_mode()).strip().lower()
    if mode not in VALID_MODES:
        mode = "signal"
    if mode == "all":
        return True
    if mode == "off":
        return False
    return has_signal(subject, body)


def suppressed_reason(mode: str | None = None) -> str:
    mode = (mode or notify_mode()).strip().lower()
    if mode == "off":
        return "closer notifications disabled; telemetry retained locally"
    return "routine closer notification suppressed (signal-only); telemetry retained locally"
