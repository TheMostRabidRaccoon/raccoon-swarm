"""Closer telemetry should not imply every session merits interruption."""
import swarm_closer_policy as cp


def test_default_mode_is_signal(monkeypatch):
    monkeypatch.delenv("RRI_CLOSER_NOTIFY_MODE", raising=False)
    assert cp.notify_mode() == "signal"


def test_clean_digest_is_quiet_in_signal_mode():
    subject = "Swarm Closer — Session x — clean"
    body = "## What needs you\n- (nothing flagged for your attention)\n\n## What's owed\n- (none)"
    assert cp.should_notify(subject, body, mode="signal") is False


def test_blocker_review_and_flag_interrupt_even_if_subject_says_clean():
    subject = "Swarm Closer — Session x — clean"
    for cue in ("[BLOCKER] broken", "[REVIEW] inspect this", "[FLAG] uncertainty"):
        assert cp.should_notify(subject, f"## What needs you\n- {cue}", mode="signal") is True


def test_model_issue_or_gap_subject_interrupts():
    assert cp.should_notify("Swarm Closer — Session x — gap=2", "", mode="signal") is True
    assert cp.should_notify("Swarm Closer — Session x — model issues", "", mode="signal") is True


def test_all_and_off_override_signal_detection():
    clean = "Swarm Closer — Session x — clean"
    assert cp.should_notify(clean, "", mode="all") is True
    assert cp.should_notify("Swarm Closer — x — 1 blocker(s)", "[BLOCKER] x", mode="off") is False


def test_bad_env_mode_falls_back_to_signal(monkeypatch):
    monkeypatch.setenv("RRI_CLOSER_NOTIFY_MODE", "parliament")
    assert cp.notify_mode() == "signal"
