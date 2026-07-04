"""Tests for the write-audit log + .py allowance (write-pipeline honesty).

The audit log makes the Session-133 write-reconciliation gap observable: every
filestore write records which seat, which path, via which CHANNEL (tool =
synchronous mid-turn; directive = round-boundary async) and RESULT. And .py is
now a storable extension so Tiny Tool Invention can persist a test_stub.py.
"""
import json

import swarm_filestore as fs
import swarm_tools


def _audit_lines(storage):
    p = fs._storage_root() / "logs" / "write-audit.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


# ---- .py allowance -------------------------------------------------------

def test_py_write_now_allowed(storage):
    # The Tiny Tool DoD wanted test_stub.py; the old allowlist forced .py.txt.
    assert fs.write_file("joy/tools/wc/test_stub.py", "def test_x():\n    assert True\n") is True
    assert "def test_x" in fs.read_file("joy/tools/wc/test_stub.py")


def test_py_is_listed_and_searched(storage):
    fs.write_file("joy/tools/wc/test_stub.py", "def test_word_counter(): assert True")
    assert "joy/tools/wc/test_stub.py" in fs.list_files("joy")
    hits = fs.search_files("word_counter", subdir="joy")
    assert any(h["path"] == "joy/tools/wc/test_stub.py" for h in hits)


def test_traversal_still_blocked_with_py(storage):
    # Adding .py must not weaken traversal safety: any ".." segment is rejected.
    assert fs.write_file("joy/../escape.py", "x") is False
    assert fs.write_file("positions/../../outside.py", "x") is False


# ---- audit log: directive channel ----------------------------------------

def test_directive_writes_audited(storage):
    rounds = {
        "grok": "[MEMORY_WRITE: positions/real.md]\nbody\n[/MEMORY_WRITE]",
        # a rejected write: bad extension -> recorded as rejected, not silently lost
        "gpt": "[MEMORY_WRITE: positions/bad.exe]\nx\n[/MEMORY_WRITE]",
    }
    fs.process_round_writes(rounds)
    lines = _audit_lines(storage)
    by_path = {l["path"]: l for l in lines}
    assert by_path["positions/real.md"]["channel"] == "directive"
    assert by_path["positions/real.md"]["result"] == "written"
    assert by_path["positions/real.md"]["model"] == "grok"
    # The rejected write is captured — the "silent rejection" phantom-cause, seen.
    assert by_path["positions/bad.exe"]["result"] == "rejected"


# ---- audit log: tool channel ---------------------------------------------

def test_tool_writes_audited(storage):
    swarm_tools.dispatch("filestore_write",
                         {"path": "positions/via-tool.md", "content": "hi"},
                         calling_model="claude")
    swarm_tools.dispatch("filestore_write",
                         {"path": "positions/../nope.md", "content": "x"},
                         calling_model="claude")
    lines = _audit_lines(storage)
    tool = [l for l in lines if l["channel"] == "tool"]
    by_path = {l["path"]: l for l in tool}
    assert by_path["positions/via-tool.md"]["result"] == "written"
    assert by_path["positions/via-tool.md"]["model"] == "claude"
    assert by_path["positions/../nope.md"]["result"] == "rejected"


def test_both_channels_distinguishable(storage):
    # The whole point: the same path written two ways is tagged by channel, so
    # phantom rates stay comparable across seats.
    swarm_tools.dispatch("filestore_write", {"path": "positions/x.md", "content": "a"},
                         calling_model="claude")
    fs.process_round_writes({"grok": "[MEMORY_WRITE: positions/y.md]\nb\n[/MEMORY_WRITE]"})
    channels = {l["path"]: l["channel"] for l in _audit_lines(storage)}
    assert channels["positions/x.md"] == "tool"
    assert channels["positions/y.md"] == "directive"


def test_audit_never_raises(storage, monkeypatch):
    # Telemetry must never break a real write, even if the audit file is unwritable.
    monkeypatch.setattr(fs, "_storage_root", lambda: (_ for _ in ()).throw(OSError("boom")))
    fs.audit_write(model="grok", path="positions/z.md", channel="directive", result="written")
    # no exception == pass
