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
    assert fs._resolve_safe("positions/thing.py") is None
    assert fs._resolve_safe("positions/thing") is None


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
