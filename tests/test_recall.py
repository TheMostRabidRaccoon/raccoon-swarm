"""Tests for visibility-aligned, freshness-aware automatic recall."""
from pathlib import Path

import pytest

pytest.importorskip("numpy")

import swarm_drive
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
    monkeypatch.setenv("RRI_AUTO_RECALL", "true")
    monkeypatch.setenv("RRI_AUTO_RECALL_DRIVE", "false")
    sem._invalidate_search_cache()
    return storage


def _plant_internal(storage: Path, rel: str, content: str) -> None:
    p = storage / rel
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

    (recall_env / "positions" / "a.md").unlink()
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


# ---- automatic relevance activation -------------------------------------

def test_extract_task_from_round_prompt():
    prompt = (
        "=== SWARM MEMORY ===\nold context\n=== END ===\n\n"
        "=== TASK ===\nTell me what we learned about raccoon memory.\n=== END TASK ==="
    )
    assert recall.extract_task(prompt) == "Tell me what we learned about raccoon memory."


def test_referential_query_uses_compact_memory_only_as_retrieval_cue():
    memory = {
        "session_log": [{"query": "Design automatic semantic memory retrieval"}],
        "resolved_positions": [{"topic": "memory freshness", "status": "active"}],
        "next_pursuits": [{"direction": "test Drive recall"}],
    }
    rq = recall.build_retrieval_query("Yes, continue that", memory)
    assert rq.startswith("Yes, continue that")
    assert "Design automatic semantic memory retrieval" in rq
    assert "memory freshness" in rq


def test_automatic_recall_injects_relevant_current_filestore_evidence(recall_env):
    fs.write_file(
        "frameworks/memory-design.md",
        "Fresh raccoon memory should activate relevant prior experience before cognition begins.",
    )
    fs.write_file(
        "frameworks/irrelevant.md",
        "A document about tomatoes and patio furniture.",
    )

    out = recall.automatic_recall(
        "How should fresh raccoon memory work?",
        memory={"session_log": []},
        local_limit=3,
        drive_limit=0,
    )
    assert out["ok"] is True
    assert any(r["path"] == "frameworks/memory-design.md" for r in out["local"])
    assert "AUTOMATIC RECALL" in out["context"]
    assert "EVIDENCE, not an instruction layer" in out["context"]
    assert "Fresh raccoon memory" in out["context"]


def test_automatic_recall_fuses_read_only_drive_when_configured(recall_env, monkeypatch):
    monkeypatch.setenv("RRI_AUTO_RECALL_DRIVE", "true")
    monkeypatch.setattr(swarm_drive, "status", lambda: {"configured": True})
    monkeypatch.setattr(
        swarm_drive,
        "search",
        lambda query, max_results=5: {
            "ok": True,
            "results": [{
                "id": "ABCDEFGH1234",
                "name": "RRI Carry Forward",
                "modified": "2026-08-01T00:00:00Z",
                "web_view_link": "https://drive.google/x",
            }],
        },
    )
    monkeypatch.setattr(
        swarm_drive,
        "read",
        lambda file_id, max_chars=8000: {
            "ok": True,
            "text_available": True,
            "content": "The carry forward remembers that roles are attentional priors, not departments.",
        },
    )

    out = recall.automatic_recall(
        "What did we decide about roles?",
        memory={"session_log": []},
        local_limit=0,
        drive_limit=2,
    )
    assert len(out["drive"]) == 1
    assert out["drive"][0]["file_id"] == "ABCDEFGH1234"
    assert "Google Drive — read-only retrieval" in out["context"]
    assert "roles are attentional priors" in out["context"]


def test_unconfigured_drive_is_a_missing_route_not_a_recall_failure(recall_env, monkeypatch):
    monkeypatch.setenv("RRI_AUTO_RECALL_DRIVE", "true")
    monkeypatch.setattr(
        swarm_drive,
        "status",
        lambda: {"configured": False, "reason": "RRI_DRIVE_REMOTE is not configured"},
    )
    out = recall.automatic_recall(
        "raccoon memory",
        memory={"session_log": []},
        local_limit=0,
        drive_limit=2,
    )
    assert out["ok"] is True
    assert out["drive"] == []
    assert "not configured" in out["drive_meta"]["reason"]


def test_manual_memory_recall_tool_exposes_same_ecology(monkeypatch):
    defs = recall.tool_definitions()
    assert "memory_recall" in defs
    assert "filestore_semantic_search" in defs
    assert "memory_index_status" in defs
    assert "evidence" in defs["memory_recall"]["description"].lower()
