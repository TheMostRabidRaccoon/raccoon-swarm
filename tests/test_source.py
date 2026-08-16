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


def test_tool_definitions_are_observation_only():
    defs = src.tool_definitions()
    assert set(defs) == {"source_status", "source_list", "source_read", "source_search"}
    joined = " ".join(spec["description"].lower() for spec in defs.values())
    assert "read-only" in joined
    assert "production-write" in joined or "mutation" in joined
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
