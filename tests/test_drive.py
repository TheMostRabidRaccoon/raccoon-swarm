"""Tests for the read-only Google Drive observation surface."""
from pathlib import Path
from types import SimpleNamespace
import json
import zipfile

import pytest

import swarm_drive as drive


def test_status_describes_missing_route_without_global_incapacity(monkeypatch):
    monkeypatch.delenv("RRI_DRIVE_REMOTE", raising=False)
    out = drive.status()
    assert out["configured"] is False
    assert out["remote_write_actuator"] == "not exposed on this surface"
    assert "RRI_DRIVE_REMOTE" in out["reason"]


def test_drive_query_uses_fulltext_and_escapes_literals():
    q = drive._drive_query("RRI swarm's memory")
    assert "trashed = false" in q
    assert "fullText contains 'RRI'" in q
    assert "fullText contains 'swarm\\'s'" in q
    assert "fullText contains 'memory'" in q


def test_search_uses_provider_fulltext_query_and_returns_ids(monkeypatch):
    monkeypatch.setattr(drive, "_configured", lambda: (True, "configured"))
    monkeypatch.setattr(drive, "_remote", lambda: "gdrive:")
    seen = {}

    payload = [
        {"id": "BBBBBBBB", "name": "other notes", "mimeType": "text/plain", "modifiedTime": "2026-01-01T00:00:00Z"},
        {"id": "AAAAAAAA", "name": "RRI memory design", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "2026-08-01T00:00:00Z", "webViewLink": "https://drive.google/x"},
    ]

    def fake_run(args, timeout=None):
        seen["args"] = args
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(drive, "_run", fake_run)
    out = drive.search("RRI memory", max_results=5)
    assert out["ok"] is True
    assert seen["args"][:4] == ["rclone", "backend", "query", "gdrive:"]
    assert "fullText contains" in seen["args"][4]
    assert out["results"][0]["id"] == "AAAAAAAA"
    assert out["results"][0]["name"] == "RRI memory design"


def test_read_caps_transfer_before_local_file_is_admitted(monkeypatch):
    monkeypatch.setattr(drive, "_configured", lambda: (True, "configured"))
    monkeypatch.setattr(drive, "_remote", lambda: "gdrive:")
    seen = {}

    def fake_run(args, timeout=None):
        seen["args"] = args
        dest = Path(args[5])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "Memory Notes.txt").write_text(
            "remember the White Rose and the checker is also blind"
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(drive, "_run", fake_run)
    out = drive.read("ABCDEFGH1234", max_chars=1000)
    assert out["ok"] is True
    assert out["text_available"] is True
    assert "checker is also blind" in out["content"]
    assert seen["args"][:4] == ["rclone", "backend", "copyid", "gdrive:"]
    assert seen["args"][4] == "ABCDEFGH1234"
    assert "--drive-export-formats" in seen["args"]
    assert "--max-size" in seen["args"]
    assert "--max-transfer" in seen["args"]
    assert "--cutoff-mode" in seen["args"]
    cutoff_i = seen["args"].index("--cutoff-mode")
    assert seen["args"][cutoff_i + 1] == "HARD"
    # No remote mutation verb is exposed by the read implementation.
    assert not any(v in seen["args"] for v in ("delete", "move", "purge", "rcat", "copyto"))


def test_transfer_failure_does_not_attempt_extraction(monkeypatch):
    monkeypatch.setattr(drive, "_configured", lambda: (True, "configured"))
    monkeypatch.setattr(drive, "_remote", lambda: "gdrive:")
    monkeypatch.setattr(
        drive,
        "_run",
        lambda args, timeout=None: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="max transfer limit reached",
        ),
    )
    out = drive.read("ABCDEFGH1234")
    assert out["ok"] is False
    assert "max transfer limit" in out["error"]


def test_office_archive_expansion_is_bounded(tmp_path, monkeypatch):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "x" * 4096)

    monkeypatch.setattr(drive, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 1024)
    with pytest.raises(ValueError, match="archive expansion exceeds limit"):
        drive._assert_archive_safe(path)


def test_read_rejects_invalid_drive_id(monkeypatch):
    monkeypatch.setattr(drive, "_configured", lambda: (True, "configured"))
    out = drive.read("../../etc/passwd")
    assert out["ok"] is False
    assert "invalid Drive file id" in out["error"]


def test_tool_surface_contains_only_status_search_read():
    defs = drive.tool_definitions()
    assert set(defs) == {"drive_status", "drive_search", "drive_read"}
    assert not any(any(word in name for word in ("write", "delete", "move", "upload")) for name in defs)
