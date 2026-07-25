"""Path-safety and round-trip tests for swarm_filestore.

The filestore is the swarm's shared memory and is written to from model output,
so _resolve_safe() is a security boundary: a model must not be able to escape
the storage root or write outside a first-level subdirectory.
"""
import swarm_filestore as fs


# ---- _resolve_safe: things that MUST be rejected -------------------------

def test_rejects_parent_traversal(storage):
    assert fs._resolve_safe("positions/../../etc/passwd") is None
    assert fs._resolve_safe("../secrets.md") is None
    assert fs._resolve_safe("positions/../../../root/.ssh/id_rsa") is None


def test_rejects_absolute_escape(storage):
    # Leading-slash paths are normalized, but an absolute system path shape
    # (no first-level swarm subdir) must not resolve.
    assert fs._resolve_safe("/etc/passwd") is None
    assert fs._resolve_safe("etc/passwd") is None  # 'passwd' has no allowed ext


def test_rejects_root_level_file(storage):
    # A file directly at the root (no subdirectory) is not allowed.
    assert fs._resolve_safe("notes.md") is None


def test_rejects_bad_extension(storage):
    assert fs._resolve_safe("positions/thing.exe") is None
    assert fs._resolve_safe("positions/thing") is None
    # .py is now allowed (Tiny Tool test_stub.py) — inert storage, not execution.
    assert fs._resolve_safe("positions/thing.py") is not None


def test_rejects_bad_dir_name(storage):
    # Directory segment must start with a lowercase letter.
    assert fs._resolve_safe("1positions/x.md") is None
    assert fs._resolve_safe("Positions/x.md") is None
    assert fs._resolve_safe("_hidden/x.md") is None


# ---- _resolve_safe: things that MUST be accepted -------------------------

def test_accepts_simple_paths(storage):
    for ok in ("positions/anansi.md", "questions/open-q.md",
               "artifacts/calc.json", "logs/session-58.log",
               "frameworks/taxonomy.txt"):
        resolved = fs._resolve_safe(ok)
        assert resolved is not None, ok
        # Resolved path stays under the storage root.
        assert str(resolved).startswith(str(storage.resolve()))


def test_accepts_nested_and_dated(storage):
    assert fs._resolve_safe("artifacts/code-runs/2026-05-03_calc.md") is not None
    assert fs._resolve_safe("positions/2026-05-03_irs-refund.md") is not None


# ---- round trips ---------------------------------------------------------

def test_write_read_round_trip(storage):
    assert fs.write_file("positions/hello.md", "# hi\nbody") is True
    assert fs.read_file("positions/hello.md") == "# hi\nbody"


def test_write_rejected_for_unsafe_path(storage):
    assert fs.write_file("../escape.md", "x") is False
    assert fs.read_file("../escape.md") is None


def test_append_adds_separator(storage):
    assert fs.append_file("logs/s.log", "first") is True
    assert fs.append_file("logs/s.log", "second") is True
    body = fs.read_file("logs/s.log")
    assert "first" in body and "second" in body
    assert "---" in body  # separator inserted between appends


def test_list_files_scopes_to_subdir(storage):
    fs.write_file("positions/a.md", "a")
    fs.write_file("questions/b.md", "b")
    listed = fs.list_files("positions")
    assert any(p.endswith("a.md") for p in listed)
    assert not any(p.endswith("b.md") for p in listed)


# ---- unindexed_files: binaries are disclosed, not hidden ------------------

def _plant_png(storage, rel="artifacts/images/ghost.png"):
    # write_file's suffix gate correctly rejects binaries, so plant one the
    # way imagegen does: directly on disk under the storage root.
    target = storage / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return rel


def test_unindexed_files_surfaces_binaries(storage):
    rel = _plant_png(storage)
    fs.write_file("artifacts/note.md", "text")
    # The png is invisible to list_files but visible to unindexed_files.
    assert not any(p.endswith(".png") for p in fs.list_files("artifacts"))
    unindexed = fs.unindexed_files("artifacts")
    assert unindexed == [rel]
    # Text files stay out of the unindexed lane.
    assert not any(p.endswith(".md") for p in unindexed)


def test_unindexed_files_safety_rules_match_list_files(storage):
    _plant_png(storage)
    assert fs.unindexed_files("../etc") == []
    assert fs.unindexed_files("no-such-dir") == []
    # Underscore-prefixed files are internal and stay hidden everywhere.
    hidden = storage / "artifacts" / "images" / "_index.png"
    hidden.write_bytes(b"x")
    assert not any("_index" in p for p in fs.unindexed_files("artifacts"))


def test_filestore_list_dispatch_discloses_unindexed(storage):
    # swarm_tools pulls the websearch/imagegen stack (requests, etc.) which
    # bare CI doesn't install — same skip rule as test_write_audit.
    import pytest
    swarm_tools = pytest.importorskip("swarm_tools")
    rel = _plant_png(storage)
    out = swarm_tools._dispatch_filestore_list("artifacts")
    assert out["unindexed_files"] == [rel]
    assert "/artifacts/images" in out["unindexed_note"]
    # No binaries around -> the keys are absent, not empty noise.
    clean = swarm_tools._dispatch_filestore_list("positions")
    assert "unindexed_files" not in clean and "unindexed_note" not in clean
