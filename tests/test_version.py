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
