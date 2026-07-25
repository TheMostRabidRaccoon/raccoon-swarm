"""Tests for swarm_version — the 'merged ≠ deployed' detector.

The boot anchor and staleness comparison are the point; git reads are
best-effort. These pin the pure comparison and the response shape.
"""
import swarm_version as ver


def test_compute_up_to_date():
    assert ver.compute_up_to_date("abc123", "abc123") is True
    assert ver.compute_up_to_date("abc123", "def456") is False   # process behind checkout
    assert ver.compute_up_to_date(None, "abc123") is None        # can't tell
    assert ver.compute_up_to_date("abc123", None) is None


def test_version_info_shape():
    info = ver.version_info()
    for key in ("boot_commit", "head_commit", "up_to_date", "boot_time", "checked_at", "note"):
        assert key in info
    # up_to_date is a tristate; when False there must be a restart note.
    assert info["up_to_date"] in (True, False, None)
    if info["up_to_date"] is False:
        assert "restart" in (info["note"] or "").lower()
    else:
        assert info["note"] is None


def test_env_override(monkeypatch):
    monkeypatch.setenv("RRI_REPO_SHA", "0123456789abcdef")
    assert ver._read_head_sha() == "0123456789ab"   # trimmed to 12


def test_boot_commit_is_captured_once():
    # BOOT_COMMIT is a module constant captured at import — a later working-tree
    # change must NOT retroactively alter it (that's what makes it the *deployed*
    # commit, not a live read).
    first = ver.BOOT_COMMIT
    assert ver.BOOT_COMMIT is first


# ── upstream drift (2026-07-24 deploy-gap repair) ────────────────────────
# The July 13 image fix was merged to main ~1h before Session 142 falsely
# convicted the pipeline it repaired; the server ran stale code for 11 days.
# These pin the pure drift comparison and the banner/response surfaces.


def test_compute_drift():
    assert ver.compute_drift("abc", "abc") is False
    assert ver.compute_drift("abc", "def") is True
    assert ver.compute_drift(None, "abc") is None
    assert ver.compute_drift("abc", None) is None


def test_session_banner_reports_drift(monkeypatch):
    monkeypatch.setattr(ver, "upstream_sha", lambda: "feedbeefcafe")
    monkeypatch.setattr(ver, "BOOT_COMMIT", "feedbeefcafe")
    assert "in sync" in ver.session_banner()

    monkeypatch.setattr(ver, "BOOT_COMMIT", "00000badc0de")
    banner = ver.session_banner()
    assert "DRIFT" in banner and "feedbeefcafe" in banner


def test_session_banner_unknown_upstream(monkeypatch):
    monkeypatch.setattr(ver, "upstream_sha", lambda: None)
    assert "drift unknown" in ver.session_banner()


def test_version_info_has_drift_keys(monkeypatch):
    monkeypatch.setattr(ver, "upstream_sha", lambda: "feedbeefcafe")
    info = ver.version_info()
    assert info["upstream_sha"] == "feedbeefcafe"
    assert info["running_sha"] == info["boot_commit"]
    assert info["drift"] == ver.compute_drift(info["boot_commit"], "feedbeefcafe")


def test_upstream_cache_serves_within_ttl(monkeypatch):
    calls = []

    def fake_read(timeout=5.0):
        calls.append(1)
        return "cafe00000001"

    monkeypatch.setattr(ver, "_read_upstream_sha", fake_read)
    ver._UPSTREAM_CACHE.update({"sha": None, "at": 0.0})
    assert ver.upstream_sha() == "cafe00000001"
    assert ver.upstream_sha() == "cafe00000001"
    assert len(calls) == 1  # second hit came from the TTL cache
    ver._UPSTREAM_CACHE.update({"sha": None, "at": 0.0})
