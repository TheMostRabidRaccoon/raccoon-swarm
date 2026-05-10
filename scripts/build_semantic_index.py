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
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env from the repo root so OPENAI_API_KEY (and friends) are present
# whether this script is invoked from systemd (which has EnvironmentFile=)
# or from a shell that hasn't sourced .env. Best-effort — the script will
# error cleanly downstream if the key still isn't set.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

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
