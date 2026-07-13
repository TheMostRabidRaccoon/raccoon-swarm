"""Compost sweep tests — the janitor for ephemeral code runs.

The sweep's one hard rule: every ambiguity fails toward keeping. Only a run
whose manifest explicitly says "ephemeral": true AND whose timestamp is
parseable AND old enough may move — and even then only into _composted/,
never deleted.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import swarm_codeexec
import swarm_filestore as fs


def _plant_run(storage, run_id, *, ephemeral=None, age_days=0, manifest=True):
    """Fabricate a persisted code run under artifacts/code-runs/<run_id>/."""
    run_dir = storage / "artifacts" / "code-runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "main.py").write_text("print('x')")
    (run_dir / "stdout.txt").write_text("x")
    if manifest:
        body = {
            "run_id": run_id,
            "timestamp": (datetime.now() - timedelta(days=age_days)).isoformat(),
        }
        if ephemeral is not None:
            body["ephemeral"] = ephemeral
        (run_dir / "manifest.json").write_text(json.dumps(body))
    return run_dir


def test_persist_run_stamps_ephemeral(storage):
    swarm_codeexec._persist_run(
        run_id="2026-07-13_000001", code="pass", description="a bit",
        model="test", stdout="", stderr="", exit_code=0, timed_out=False,
        elapsed_ms=1, generated_paths=[], ephemeral=True,
    )
    manifest = json.loads(
        (storage / "artifacts" / "code-runs" / "2026-07-13_000001" / "manifest.json").read_text()
    )
    assert manifest["ephemeral"] is True


def test_persist_run_defaults_to_keep(storage):
    swarm_codeexec._persist_run(
        run_id="2026-07-13_000002", code="pass", description="real work",
        model="test", stdout="", stderr="", exit_code=0, timed_out=False,
        elapsed_ms=1, generated_paths=[],
    )
    manifest = json.loads(
        (storage / "artifacts" / "code-runs" / "2026-07-13_000002" / "manifest.json").read_text()
    )
    assert manifest["ephemeral"] is False


def test_sweep_composts_only_old_ephemeral(storage):
    old_bit = _plant_run(storage, "old-bit", ephemeral=True, age_days=30)
    young_bit = _plant_run(storage, "young-bit", ephemeral=True, age_days=1)
    old_real = _plant_run(storage, "old-real", ephemeral=False, age_days=30)
    unmarked = _plant_run(storage, "old-unmarked", age_days=30)  # no ephemeral key
    orphan = _plant_run(storage, "old-orphan", age_days=30, manifest=False)

    result = swarm_codeexec.compost_sweep(older_than_days=7)

    assert result["ok"] is True
    assert result["swept"] == ["old-bit"]
    assert result["kept_young"] == ["young-bit"]
    # The move is reversible — the run lives on under _composted/.
    assert not old_bit.exists()
    assert (storage / "artifacts" / "code-runs" / "_composted" / "old-bit" / "manifest.json").exists()
    # Everything ambiguous or honest stayed put.
    for kept in (young_bit, old_real, unmarked, orphan):
        assert kept.exists()


def test_sweep_dry_run_moves_nothing(storage):
    run = _plant_run(storage, "old-bit", ephemeral=True, age_days=30)
    result = swarm_codeexec.compost_sweep(older_than_days=7, dry_run=True)
    assert result["swept"] == ["old-bit"] and result["dry_run"] is True
    assert run.exists()
    assert not (storage / "artifacts" / "code-runs" / "_composted").exists()


def test_sweep_is_idempotent_and_skips_compost_dir(storage):
    _plant_run(storage, "old-bit", ephemeral=True, age_days=30)
    swarm_codeexec.compost_sweep(older_than_days=7)
    second = swarm_codeexec.compost_sweep(older_than_days=7)
    assert second["swept"] == [] and second["ok"] is True
    # Still exactly one copy, still recoverable.
    assert (storage / "artifacts" / "code-runs" / "_composted" / "old-bit").exists()


def test_composted_runs_leave_every_filestore_lane(storage):
    _plant_run(storage, "old-bit", ephemeral=True, age_days=30)
    assert any("old-bit" in p for p in fs.list_files("artifacts"))
    assert any("old-bit" in r["path"] for r in fs.search_files("old-bit"))
    swarm_codeexec.compost_sweep(older_than_days=7)
    listed = fs.list_files("artifacts")
    assert not any("old-bit" in p for p in listed)
    assert not any("_composted" in p for p in listed)
    assert not any("old-bit" in p for p in fs.unindexed_files("artifacts"))
    assert not any("old-bit" in r.get("path", "") for r in fs.search_files("old-bit"))
