"""Tests for the read-only Google Drive observation surface."""
from types import SimpleNamespace
from pathlib import Path
import json

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


def test_read_fetches_by_id_to_local_temp_and_extracts_text(monkeypatch):
    monkeypatch.setattr(drive, "_configured", lambda: (True, "configured"))
    monkeypatch.setattr(drive, "_remote", lambda: "gdrive:")
    seen = {}

    def fake_run(args, timeout=None):
        seen["args"] = args
        # Last positional destination is immediately after the file id.
        dest = Path(args[5])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "Memory Notes.txt").write_text("remember the White Rose and the checker is also blind")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(drive, "_run", fake_run)
    out = drive.read("ABCDEFGH1234", max_chars=1000)
    assert out["ok"] is True
    assert out["text_available"] is True
    assert "checker is also blind" in out["content"]
    assert seen["args"][:4] == ["rclone", "backend", "copyid", "gdrive:"]
    assert seen["args"][4] == "ABCDEFGH1234"
    assert "--drive-export-formats" in seen["args"]
    # No remote mutation verb is exposed by the read implementation.
    assert not any(v in seen["args"] for v in ("delete", "move", "purge", "rcat", "copyto"))


def test_read_rejects_invalid_drive_id(monkeypatch):
    monkeypatch.setattr(drive, "_configured", lambda: (True, "configured"))
    out = drive.read("../../etc/passwd")
    assert out["ok"] is False
    assert "invalid Drive file id" in out["error"]


def test_tool_surface_contains_only_status_search_read():
    defs = drive.tool_definitions()
    assert set(defs) == {"drive_status", "drive_search", "drive_read"}
    assert not any(any(word in name for word in ("write", "delete", "move", "upload")) for name in defs)
