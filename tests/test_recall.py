"""Tests for visibility-aligned, freshness-aware durable-memory recall."""
from pathlib import Path

import pytest

pytest.importorskip("numpy")

import swarm_filestore as fs
import swarm_recall as recall
import swarm_semantic as sem


_VOCAB = ["raccoon", "memory", "compost", "fresh", "new", "governance"]


def _fake_vec(text):
    low = (text or "").lower()
    return [float(low.count(w)) + 0.1 for w in _VOCAB]


@pytest.fixture
def recall_env(storage, monkeypatch):
    monkeypatch.setattr(sem, "_embed_batch", lambda texts: [_fake_vec(t) for t in texts])
    monkeypatch.setattr(sem, "_embed_one", lambda text: _fake_vec(text))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("RRI_SEMANTIC_AUTO_REFRESH", "true")
    sem._invalidate_search_cache()
    return storage


def _plant_internal(storage: Path, rel: str, content: str) -> None:
    p = storage / "swarm" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_reindex_uses_model_visible_filestore_surface(recall_env):
    fs.write_file("positions/keep.md", "A durable raccoon memory that should be recalled.")
    _plant_internal(
        recall_env,
        "artifacts/code-runs/_composted/old-bit/stdout.txt",
        "raccoon compost joke that must stay out of active recall",
    )

    summary = recall.reindex_visible(force=True)
    assert summary["ok"] is True
    index = sem._load_index()
    paths = set(index["files"])
    assert "positions/keep.md" in paths
    assert not any("_composted" in p for p in paths)
    assert summary["visibility_surface"] == "filestore.list_files"


def test_freshness_detects_new_changed_and_removed_memory(recall_env):
    fs.write_file("positions/a.md", "raccoon memory one")
    recall.reindex_visible(force=True)
    assert recall.freshness()["fresh"] is True

    fs.write_file("frameworks/new.md", "a new governance memory")
    fresh = recall.freshness()
    assert fresh["fresh"] is False
    assert "frameworks/new.md" in fresh["added"]

    fs.write_file("positions/a.md", "raccoon memory one changed")
    fresh = recall.freshness()
    assert "positions/a.md" in fresh["changed"]

    (recall_env / "swarm" / "positions" / "a.md").unlink()
    fresh = recall.freshness()
    assert "positions/a.md" in fresh["removed"]


def test_search_auto_refreshes_stale_index_before_recall(recall_env):
    fs.write_file("positions/a.md", "old raccoon memory")
    recall.reindex_visible(force=True)

    fs.write_file("frameworks/fresh.md", "fresh new governance memory")
    assert recall.freshness()["fresh"] is False

    out = recall.search("fresh new governance", top_k=5, hybrid=True)
    assert out["ok"] is True
    assert out["memory_index"]["refreshed"] is True
    assert out["memory_index"]["freshness"]["fresh"] is True
    assert any(r["path"] == "frameworks/fresh.md" for r in out["results"])


def test_search_filters_old_internal_chunks_even_if_index_contains_them(recall_env):
    fs.write_file("positions/keep.md", "raccoon memory visible")
    recall.reindex_visible(force=True)

    # Simulate an older/manual index that once leaked an internal chunk.
    index = sem._load_index()
    fake = {
        "path": "artifacts/code-runs/_composted/ghost/stdout.txt",
        "chunk_index": 0,
        "text": "compost raccoon ghost",
        "content_hash": "fake",
        "embedding": _fake_vec("compost raccoon ghost"),
        "meta": {"type": "artifact"},
    }
    index["chunks"].append(fake)
    index["files"][fake["path"]] = {"content_hash": "fake", "chunk_count": 1}
    sem._save_index(index)
    sem._invalidate_search_cache()

    out = recall.search("compost raccoon ghost", top_k=10)
    assert all("_composted" not in r["path"] for r in out.get("results", []))
    assert out["memory_index"]["freshness"]["fresh"] is True


def test_stale_index_reports_surface_limit_when_refresh_credential_absent(recall_env, monkeypatch):
    fs.write_file("positions/a.md", "raccoon memory")
    recall.reindex_visible(force=True)
    fs.write_file("positions/b.md", "new memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    state = recall.ensure_fresh()
    assert state["ok"] is False
    assert state["freshness"]["fresh"] is False
    assert "credential is not exposed on this surface" in state["warning"]


def test_auto_refresh_can_be_disabled_without_claiming_incapacity(recall_env, monkeypatch):
    fs.write_file("positions/a.md", "raccoon memory")
    recall.reindex_visible(force=True)
    fs.write_file("positions/b.md", "new memory")
    monkeypatch.setenv("RRI_SEMANTIC_AUTO_REFRESH", "false")

    state = recall.ensure_fresh()
    assert state["ok"] is False
    assert state["refreshed"] is False
    assert "disabled on this surface" in state["warning"]
