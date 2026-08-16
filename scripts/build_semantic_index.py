#!/usr/bin/env python3
"""Build (or rebuild) the swarm's semantic-search index.

The vector engine is a locator over the durable filestore, so the index must obey
the same visibility boundary as the filestore itself. This script therefore routes
through `swarm_recall.reindex_visible()` rather than walking raw disk directly.

Consequences:
- `_composted/` and other infrastructure-internal paths stay out of active recall;
- incremental content-hash behavior from `swarm_semantic` is preserved;
- the result includes freshness metadata against the current visible memory surface.

Pass --force to re-embed everything (use after changing the embedding model or when
an index is suspect).

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

_VENV_PY = REPO_ROOT / "venv" / "bin" / "python3"
if _VENV_PY.exists() and Path(sys.prefix).resolve() != (REPO_ROOT / "venv").resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

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

import swarm_recall  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="Re-embed every visible file regardless of content_hash.")
    args = parser.parse_args()

    try:
        result = swarm_recall.reindex_visible(force=args.force)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
