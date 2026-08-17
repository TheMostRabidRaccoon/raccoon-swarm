"""Failure-mode tests for the bounded swarm continuity cache."""
from pathlib import Path
import json

import pytest

import swarm_memory as mem


def _memory(session_count: int, topic: str = "x") -> dict:
    out = mem.empty_memory()
    out["session_count"] = session_count
    out["resolved_positions"] = [
        {"topic": topic, "consensus": f"state-{session_count}", "confidence": "high"}
    ]
    return out


def test_second_atomic_save_keeps_last_known_good_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("RRI_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(mem, "MEMORY_SEED_FILE", tmp_path / "no-seed.json")

    first = _memory(1, "first")
    mem.save_swarm_memory(first)
    target = mem.memory_file()
    backup = target.with_suffix(target.suffix + ".bak")
    assert target.exists()
    assert not backup.exists()  # there was no prior live state to back up

    second = _memory(2, "second")
    mem.save_swarm_memory(second)

    assert json.loads(target.read_text())["session_count"] == 2
    assert json.loads(backup.read_text())["session_count"] == 1
    assert not target.with_suffix(target.suffix + ".tmp").exists()


def test_corrupt_live_cache_recovers_and_restores_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("RRI_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(mem, "MEMORY_SEED_FILE", tmp_path / "no-seed.json")

    mem.save_swarm_memory(_memory(1, "recover-me"))
    mem.save_swarm_memory(_memory(2, "newer"))  # backup now contains session 1

    target = mem.memory_file()
    backup = target.with_suffix(target.suffix + ".bak")
    target.write_text('{"session_count": 2, "resolved_positions": [')

    loaded = mem.load_swarm_memory()
    assert loaded["session_count"] == 1
    assert loaded["resolved_positions"][0]["topic"] == "recover-me"
    # Recovery repairs the live file too, so the next boot does not rediscover the same corruption.
    repaired = json.loads(target.read_text())
    assert repaired["session_count"] == 1
    assert json.loads(backup.read_text())["session_count"] == 1


def test_failed_serialization_leaves_previous_live_memory_intact(tmp_path, monkeypatch):
    monkeypatch.setenv("RRI_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(mem, "MEMORY_SEED_FILE", tmp_path / "no-seed.json")

    mem.save_swarm_memory(_memory(7, "stable"))
    target = mem.memory_file()
    before = target.read_text()

    real_dump = json.dump

    def explode(obj, fp, *args, **kwargs):
        fp.write('{"partial":')
        fp.flush()
        raise RuntimeError("simulated interruption during serialization")

    monkeypatch.setattr(mem.json, "dump", explode)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        mem.save_swarm_memory(_memory(8, "should-not-land"))

    monkeypatch.setattr(mem.json, "dump", real_dump)
    assert target.read_text() == before
    assert mem.load_swarm_memory()["session_count"] == 7
    assert not target.with_suffix(target.suffix + ".tmp").exists()


def test_missing_live_file_can_recover_from_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("RRI_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(mem, "MEMORY_SEED_FILE", tmp_path / "no-seed.json")

    mem.save_swarm_memory(_memory(3, "backup-source"))
    mem.save_swarm_memory(_memory(4, "current"))
    target = mem.memory_file()
    backup = target.with_suffix(target.suffix + ".bak")
    assert backup.exists()
    target.unlink()

    loaded = mem.load_swarm_memory()
    assert loaded["session_count"] == 3
    assert target.exists()
    assert json.loads(target.read_text())["session_count"] == 3


def test_bad_live_and_bad_backup_fall_back_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setenv("RRI_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(mem, "MEMORY_SEED_FILE", tmp_path / "no-seed.json")

    target = mem.memory_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not-json")
    target.with_suffix(target.suffix + ".bak").write_text("also-not-json")

    loaded = mem.load_swarm_memory()
    assert loaded == mem.empty_memory()
