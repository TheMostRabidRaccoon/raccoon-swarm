"""Swarm code execution — sandboxed Python runner with auto-capture.

Lets the swarm verify quantitative claims by actually executing code instead
of narrating math. Outputs (stdout, stderr, generated files) get persisted
to /artifacts/code-runs/ via the filestore so they survive across sessions.

Sandbox constraints:
- timeout: configurable up to MAX_TIMEOUT seconds (default 60)
- memory: RLIMIT_AS cap (default 1024 MB)
- env vars: stripped to a safe minimum (PATH, HOME, LANG)
- cwd: ephemeral tempdir per run, deleted after capture
- network: best-effort isolation via `unshare -rn` if available; otherwise
  the venv simply lacks network libraries (requests, etc.) — stdlib's
  urllib is still importable, so this is best-effort, not a security
  boundary. Single-user homelab threat model only.

This is NOT a real isolation layer. Don't expose this server publicly
without swapping in Docker or a proper sandbox (firejail, gVisor).
"""
from __future__ import annotations

import json
import os
import resource
import shutil
import signal
import subprocess
import tempfile
import time
import logging
from datetime import datetime
from pathlib import Path

import swarm_filestore

logger = logging.getLogger("SwarmVault")

DEFAULT_TIMEOUT = 60
MAX_TIMEOUT = 120
DEFAULT_MEMORY_MB = 1024
ARTIFACTS_SUBDIR = "artifacts"
RUNS_PREFIX = "code-runs"

SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")


def _has_unshare() -> bool:
    return shutil.which("unshare") is not None


# Tri-state result of probing whether `unshare -rn` actually works on this
# kernel. Unprivileged user namespaces can be disabled (kernel.unprivileged_userns_clone=0
# on some distros), in which case unshare exists but fails at runtime. We
# probe once at module load and cache the result.
#   None = not yet probed
#   True = unshare -rn works; we'll use it for network isolation
#   False = unshare -rn fails on this kernel; fall back to no-namespace mode
_UNSHARE_NET_OK: bool | None = None


def _probe_unshare_net() -> bool:
    """One-time probe: does `unshare -rn` actually work? Cached after first call."""
    global _UNSHARE_NET_OK
    if _UNSHARE_NET_OK is not None:
        return _UNSHARE_NET_OK
    if not _has_unshare():
        _UNSHARE_NET_OK = False
        logger.warning(
            "swarm_codeexec: `unshare` binary not found. Network isolation disabled. "
            "code_exec will run without a network namespace; the venv's lack of network "
            "libs is the only barrier to outbound calls."
        )
        return False
    try:
        proc = subprocess.run(
            ["unshare", "-rn", "--", "true"],
            capture_output=True,
            timeout=5,
        )
        ok = proc.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        ok = False
        logger.warning(f"swarm_codeexec: unshare probe raised {type(e).__name__}: {e}")
    _UNSHARE_NET_OK = ok
    if ok:
        logger.info("swarm_codeexec: unshare -rn probe OK; network isolation active.")
    else:
        logger.warning(
            "swarm_codeexec: unshare -rn probe FAILED (likely unprivileged user "
            "namespaces disabled on this kernel). Network isolation will not be "
            "applied. To enable: sudo sysctl -w kernel.unprivileged_userns_clone=1 "
            "(and persist via /etc/sysctl.d/). Sandbox still enforces timeout, memory, "
            "tempdir, and env-var restrictions."
        )
    return ok


def _build_command(code_path: Path, allow_network: bool) -> list[str]:
    """Build the subprocess argv. Wrap with unshare -rn for network isolation
    if the kernel supports it and allow_network=False.

    Uses sys.executable so the subprocess inherits the same Python interpreter
    (and therefore the same venv site-packages) as the swarm process. Bare
    'python3' on PATH resolves to system Python on most servers, which lacks
    numpy/pandas/etc. and produces ModuleNotFoundError mid-tool-call.
    """
    import sys
    py = sys.executable or "python3"
    base = [py, "-I", str(code_path)]  # -I: isolated mode, no user site, no PYTHONPATH
    if not allow_network and _probe_unshare_net():
        # unshare -rn: new user + network namespace — empty network stack
        return ["unshare", "-rn", "--"] + base
    return base


def _make_preexec(memory_mb: int):
    """Build a preexec_fn that sets RLIMIT_AS in the child and starts a new
    process group so we can SIGKILL the whole group on timeout."""
    def _set_limits():
        # Memory limit — RLIMIT_AS is virtual address space size in bytes
        bytes_cap = memory_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (bytes_cap, bytes_cap))
        except (ValueError, OSError):
            pass
        # New process group so we can kill any subprocess the code spawned
        os.setsid()
    return _set_limits


def _unescape_double_escaped(code: str) -> str:
    """Defensive fix for models that double-escape control chars in tool args.

    Some models (Grok in particular at the May 2026 release) generate the
    `code` parameter as a single-line string with LITERAL "\\n" sequences
    (backslash + 'n' as two chars) instead of real newline characters. The
    resulting Python file fails to parse with "unexpected character after
    line continuation character" because Python sees `import numpy as np\\n...`
    as one statement and chokes on the bare backslash.

    Heuristic: if the submitted code has zero real newlines AND contains
    "\\n" sequences, it's almost certainly double-escaped — replace `\\n`,
    `\\t`, `\\r` with their real counterparts. We only fire the conversion
    on the no-real-newlines signal so we don't accidentally rewrite legit
    Python that happens to contain `print("\\n")` or similar.
    """
    if "\n" in code:
        return code
    if "\\n" not in code:
        return code
    return code.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")


def run_code(
    code: str,
    description: str = "",
    timeout: int = DEFAULT_TIMEOUT,
    memory_mb: int = DEFAULT_MEMORY_MB,
    allow_network: bool = False,
    persist: bool = True,
    model: str = "unknown",
) -> dict:
    """Execute Python code in a sandboxed subprocess.

    Returns a dict with: stdout, stderr, exit_code, execution_time_ms,
    generated_files (relative paths in artifacts), artifact_path (the manifest),
    and a 'truncated' flag if outputs were capped.

    Outputs over 100KB are truncated; the full content lives in the persisted
    artifact directory.
    """
    timeout = max(1, min(timeout, MAX_TIMEOUT))
    started = time.monotonic()
    timestamp = datetime.now()
    run_id = timestamp.strftime("%Y-%m-%d_%H%M%S")

    # Write the code to a temp file the subprocess will execute
    workdir = Path(tempfile.mkdtemp(prefix="swarm_exec_"))
    try:
        code_path = workdir / "main.py"
        code_path.write_text(_unescape_double_escaped(code))

        env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["MPLBACKEND"] = "Agg"  # so matplotlib never tries to open a display

        cmd = _build_command(code_path, allow_network)
        # NOTE: preexec_fn warning under multithreaded callers is acceptable here.
        proc = subprocess.Popen(
            cmd,
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_make_preexec(memory_mb),
        )

        timed_out = False
        try:
            stdout_b, stderr_b = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the whole process group — matches setsid in preexec
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            stdout_b, stderr_b = proc.communicate()
            timed_out = True

        elapsed_ms = int((time.monotonic() - started) * 1000)
        stdout = stdout_b.decode(errors="replace")
        stderr = stderr_b.decode(errors="replace")

        # Detect generated files (anything new in workdir besides main.py)
        generated = sorted(
            p for p in workdir.iterdir()
            if p.is_file() and p.name != "main.py"
        )

        # Truncation policy for inline return — full content goes to the artifact
        TRUNC = 100_000
        truncated = False
        stdout_inline = stdout
        stderr_inline = stderr
        if len(stdout) > TRUNC:
            stdout_inline = stdout[:TRUNC] + f"\n[...truncated {len(stdout)-TRUNC} chars; see artifact]"
            truncated = True
        if len(stderr) > TRUNC:
            stderr_inline = stderr[:TRUNC] + f"\n[...truncated {len(stderr)-TRUNC} chars; see artifact]"
            truncated = True

        result = {
            "stdout": stdout_inline,
            "stderr": stderr_inline,
            "exit_code": -9 if timed_out else proc.returncode,
            "timed_out": timed_out,
            "execution_time_ms": elapsed_ms,
            "generated_files": [],
            "artifact_path": None,
            "truncated": truncated,
            "model": model,
            "description": description,
            "run_id": run_id,
        }

        if persist:
            try:
                _persist_run(
                    run_id=run_id,
                    code=code,
                    description=description,
                    model=model,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=result["exit_code"],
                    timed_out=timed_out,
                    elapsed_ms=elapsed_ms,
                    generated_paths=generated,
                )
                # After persist, generated_files refers to artifact-relative paths
                if generated:
                    base = f"{ARTIFACTS_SUBDIR}/{RUNS_PREFIX}/{run_id}"
                    result["generated_files"] = [f"{base}/{p.name}" for p in generated]
                result["artifact_path"] = f"{ARTIFACTS_SUBDIR}/{RUNS_PREFIX}/{run_id}/manifest.json"
            except Exception as e:  # never let persist failure break the call
                logger.error(f"swarm_codeexec persist failed: {e}")

        return result

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ============================================================
# Persist a run as artifacts under /artifacts/code-runs/<run_id>/
# ============================================================

def _persist_run(
    run_id: str,
    code: str,
    description: str,
    model: str,
    stdout: str,
    stderr: str,
    exit_code: int,
    timed_out: bool,
    elapsed_ms: int,
    generated_paths: list[Path],
) -> None:
    swarm_filestore.ensure_layout()
    root = swarm_filestore._storage_root()
    runs_dir = root / ARTIFACTS_SUBDIR / RUNS_PREFIX / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Code, stdout, stderr — written verbatim
    (runs_dir / "main.py").write_text(code)
    (runs_dir / "stdout.txt").write_text(stdout)
    (runs_dir / "stderr.txt").write_text(stderr)

    # Copy generated files
    for src in generated_paths:
        try:
            shutil.copy2(src, runs_dir / src.name)
        except OSError as e:
            logger.error(f"swarm_codeexec failed to copy {src.name}: {e}")

    manifest = {
        "run_id": run_id,
        "model": model,
        "description": description,
        "timestamp": datetime.now().isoformat(),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "execution_time_ms": elapsed_ms,
        "generated_files": [p.name for p in generated_paths],
        "stdout_size": len(stdout),
        "stderr_size": len(stderr),
    }
    (runs_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


# ============================================================
# Diagnostics
# ============================================================

def status() -> dict:
    """Snapshot of sandbox capabilities for /codeexec/status."""
    unshare_present = _has_unshare()
    unshare_works = _probe_unshare_net() if unshare_present else False
    if unshare_works:
        net_iso = "unshare -rn (linux namespaces) — active"
    elif unshare_present:
        net_iso = "unshare present but probe failed (kernel.unprivileged_userns_clone=0?) — DISABLED"
    else:
        net_iso = "unshare not installed — DISABLED"
    return {
        "max_timeout_seconds": MAX_TIMEOUT,
        "default_timeout_seconds": DEFAULT_TIMEOUT,
        "default_memory_mb": DEFAULT_MEMORY_MB,
        "network_isolation": net_iso,
        "python": shutil.which("python3"),
        "isolation_strength": "homelab-grade — do not expose publicly without docker/firejail",
    }
