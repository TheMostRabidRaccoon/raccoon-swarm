#!/usr/bin/env python3
"""Build (or rebuild) the swarm's semantic-search index.

Walks the filestore, chunks every text file, embeds each chunk via
OpenAI text-embedding-3-small, and writes the index to
<storage_root>/swarm/_semantic_index/index.json.

Idempotent — only re-embeds files whose content_hash has changed.
Pass --force to re-embed everything (use after upgrading the
embedding model, or if the index is suspect).

Usage:
  ./scripts/build_semantic_index.py
  ./scripts/build_semantic_index.py --force
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Auto-reexec under the repo venv if we landed on a system Python that
# doesn't have our deps. Without this guard, dotenv silently fails to
# import on systems where python-dotenv lives only in venv/ — and the
# script then complains about a missing OPENAI_API_KEY because .env
# was never read. Re-running the script via os.execv preserves stdout,
# argv, and exit code semantics.
_VENV_PY = REPO_ROOT / "venv" / "bin" / "python3"
if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

# Load .env from the repo root so OPENAI_API_KEY (and friends) are present
# whether this script is invoked from systemd (which has EnvironmentFile=)
# or from a shell that hasn't sourced .env. Loud failure if dotenv is
# missing — so a misconfigured Python doesn't silently produce a bad run.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    print(
        f"WARNING: python-dotenv not importable in {sys.executable}.\n"
        f"         .env will not be loaded; expect missing-API-key errors.\n"
        f"         Fix: {_VENV_PY} -m pip install python-dotenv\n"
        f"         Or: run the script via the venv directly:\n"
        f"             {_VENV_PY} {Path(__file__).resolve()}",
        file=sys.stderr,
    )

import swarm_semantic  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Re-embed every file regardless of content_hash.")
    args = parser.parse_args()

    try:
        result = swarm_semantic.reindex(force=args.force)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
