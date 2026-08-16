"""Tests for the deployed-source read-only observation surface."""
from pathlib import Path

import swarm_source as src


def _plant(root: Path, rel: str, content: str = "x") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_visible_source_excludes_secrets_runtime_and_personal_lanes(tmp_path, monkeypatch):
    monkeypatch.setattr(src, "SOURCE_ROOT", tmp_path)

    _plant(tmp_path, "swarm_ecology.py", "PEER = True\n")
    _plant(tmp_path, "swarm_runtime.py", "legacy = True\n")
    _plant(tmp_path, "docs/ARCHITECTURE.md", "peer cognitive ecology\n")
    _plant(tmp_path, "tests/test_x.py", "def test_x(): pass\n")
    _plant(tmp_path, "scripts/tool.py", "print('ok')\n")

    # Outside the source-observation surface even though some are text files.
    _plant(tmp_path, ".env", "SECRET=yes\n")
    _plant(tmp_path, "swarm_memory_seed.json", '{"personal": true}\n')
    _plant(tmp_path, "corpus/private.md", "personal corpus\n")
    _plant(tmp_path, ".claude/state/session.md", "hidden state\n")
    _plant(tmp_path, "logs/runtime.log", "runtime state\n")
    _plant(tmp_path, "swarm/positions/private.md", "filestore state\n")

    paths = {entry["path"] for entry in src.list_files(max_results=500)["files"]}
    assert "swarm_ecology.py" in paths
    assert "swarm_runtime.py" in paths
    assert "docs/ARCHITECTURE.md" in paths
    assert "tests/test_x.py" in paths
    assert "scripts/tool.py" in paths

    assert ".env" not in paths
    assert "swarm_memory_seed.json" not in paths
    assert "corpus/private.md" not in paths
    assert ".claude/state/session.md" not in paths
    assert "logs/runtime.log" not in paths
    assert "swarm/positions/private.md" not in paths


def test_read_returns_line_numbered_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(src, "SOURCE_ROOT", tmp_path)
    _plant(tmp_path, "swarm_ecology.py", "one\ntwo\nthree\nfour\n")

    out = src.read("swarm_ecology.py", start_line=2, end_line=3)
    assert out["ok"] is True
    assert out["start_line"] == 2 and out["end_line"] == 3
    assert out["content"] == "2: two\n3: three"


def test_read_rejects_paths_outside_surface(tmp_path, monkeypatch):
    monkeypatch.setattr(src, "SOURCE_ROOT", tmp_path)
    _plant(tmp_path, ".env", "SECRET=yes\n")
    _plant(tmp_path, "corpus/private.md", "nope\n")

    assert src.read(".env")["ok"] is False
    assert src.read("corpus/private.md")["ok"] is False
    assert src.read("../outside.py")["ok"] is False


def test_symlink_to_denied_file_is_never_visible_readable_or_searchable(tmp_path, monkeypatch):
    monkeypatch.setattr(src, "SOURCE_ROOT", tmp_path)
    _plant(tmp_path, ".env", "SUPER_SECRET_VALUE=ringtail\n")
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "leak.md").symlink_to(tmp_path / ".env")

    listed = {entry["path"] for entry in src.list_files(max_results=500)["files"]}
    assert "docs/leak.md" not in listed
    assert src.read("docs/leak.md")["ok"] is False
    searched = src.search("SUPER_SECRET_VALUE")
    assert searched["results"] == []


def test_symlink_to_file_outside_repository_is_rejected(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside.md"
    repo.mkdir()
    outside.write_text("OUTSIDE_BOUNDARY\n")
    monkeypatch.setattr(src, "SOURCE_ROOT", repo)
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "outside.md").symlink_to(outside)

    assert src.read("docs/outside.md")["ok"] is False
    assert "docs/outside.md" not in {e["path"] for e in src.list_files()["files"]}
    assert src.search("OUTSIDE_BOUNDARY")["results"] == []


def test_symlinked_parent_directory_is_rejected(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    external_docs = tmp_path / "external_docs"
    repo.mkdir()
    external_docs.mkdir()
    (external_docs / "note.md").write_text("PARENT_SYMLINK_SECRET\n")
    monkeypatch.setattr(src, "SOURCE_ROOT", repo)
    (repo / "docs").symlink_to(external_docs, target_is_directory=True)

    assert src.read("docs/note.md")["ok"] is False
    assert src.search("PARENT_SYMLINK_SECRET")["results"] == []


def test_search_returns_line_cited_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(src, "SOURCE_ROOT", tmp_path)
    _plant(tmp_path, "swarm_ecology.py", "roles are attentional priors\nnot jurisdictions\n")
    _plant(tmp_path, "docs/ARCHITECTURE.md", "attention elsewhere\n")

    out = src.search("attentional", max_results=10)
    assert out["ok"] is True
    assert len(out["results"]) == 1
    hit = out["results"][0]
    assert hit["path"] == "swarm_ecology.py"
    assert hit["line"] == 1
    assert "1: roles are attentional priors" in hit["snippet"]


def test_tool_bundle_composes_source_and_recall_without_mutation_actuators():
    defs = src.tool_definitions()
    assert {"source_status", "source_list", "source_read", "source_search"}.issubset(defs)
    # The same extension bundle replaces the old stale semantic-search surface and
    # exposes freshness as observable state.
    assert "filestore_semantic_search" in defs
    assert "memory_index_status" in defs

    joined = " ".join(spec["description"].lower() for spec in defs.values())
    assert "read-only" in joined
    assert "production-write" in joined or "mutation" in joined
    assert "fresh" in joined
    assert not any("write" in name or "merge" in name or "deploy" in name for name in defs)


def test_status_describes_surface_not_incapacity(tmp_path, monkeypatch):
    monkeypatch.setattr(src, "SOURCE_ROOT", tmp_path)
    _plant(tmp_path, "swarm_ecology.py", "x\n")
    for key in ("RRI_SOURCE_SHA", "RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA", "SOURCE_VERSION"):
        monkeypatch.delenv(key, raising=False)

    out = src.status()
    assert out["surface"] == "deployed-source/read-only"
    assert out["write_actuator"] == "not exposed on this surface"
    assert out["canonical_semantics"] == "swarm_ecology.py"
