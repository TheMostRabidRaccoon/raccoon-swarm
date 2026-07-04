#!/usr/bin/env python3
"""Build the evidence catalog from an allowlisted Drive folder (M1b ingest).

The Drive-facing companion to swarm_evidence.py (the M1a catalog core). It reads
a folder listing, assigns each file an origin class, and — on a real run —
catalogs each text file's content into evidence.db with provenance + dedup.

Auth-light, same contract as scripts/build_drive_index.py: it consumes
`rclone lsjson --recursive` output. Configure an rclone remote once
(`rclone config`), then either pipe a listing in or let this script run rclone.

    # 1. REVIEW FIRST (metadata only — reads NO document bodies):
    rclone lsjson gdrive:'RRI Research' --recursive | \
        scripts/build_source_catalog.py --dry-run -
    #    or:
    scripts/build_source_catalog.py --dry-run --remote gdrive: --folder 'RRI Research'

    The --dry-run manifest IS the personal-content review surface: every file
    that WOULD be ingested, with its origin class, and nothing read. Skim it,
    confirm nothing personal is in there, THEN:

    # 2. INGEST (reads bodies, writes evidence.db):
    rclone lsjson gdrive:'RRI Research' --recursive | \
        scripts/build_source_catalog.py --ingest -

Deliberately no auto-run: you review the manifest, then opt in to the read.
The origin-classing (conductor-authored vs swarm-authored under a
"Notes & Sessions" lane) is what keeps the swarm from later citing its own
sessions as independent evidence.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_VENV_PY = REPO_ROOT / "venv" / "bin" / "python3"
if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

import swarm_evidence as ev  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("source-catalog")


# ---------------------------------------------------------------------------
# Drive I/O (the only non-pure part — everything testable lives in swarm_evidence)
# ---------------------------------------------------------------------------

def load_lsjson(source: str, *, remote: "str | None", folder: "str | None") -> list:
    """Load an rclone-lsjson listing from '-' (stdin), a file path, or by running
    rclone against remote+folder."""
    if source == "-":
        return json.loads(sys.stdin.read() or "[]")
    if source:
        return json.loads(Path(source).read_text() or "[]")
    if remote:
        target = f"{remote}{folder}" if folder else remote
        out = subprocess.run(
            ["rclone", "lsjson", target, "--recursive"],
            capture_output=True, text=True, check=True).stdout
        return json.loads(out or "[]")
    raise SystemExit("no listing source: pass '-' (stdin), a file, or --remote")


def _rclone_reader(remote: str):
    """A body reader that `rclone cat`s each file (Google Docs export as text)."""
    def read_body(record: dict) -> str:
        target = f"{remote}{record['path']}"
        return subprocess.run(["rclone", "cat", target],
                              capture_output=True, text=True, check=True).stdout
    return read_body


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def print_manifest(manifest: dict) -> None:
    logger.info("=== INGEST MANIFEST (dry-run — NO document bodies were read) ===")
    logger.info(f"total files: {manifest['total_files']}  "
                f"ingestable: {manifest['ingestable']}  "
                f"skipped (non-text): {manifest['skipped_non_text']}")
    logger.info(f"by origin: {manifest['by_origin']}")
    logger.info(f"by type:   {manifest['by_mime']}")
    logger.info("--- files that WOULD be catalogued (review for personal content) ---")
    for f in manifest["files"]:
        logger.info(f"  [{f['origin']:<18}] {f['path']}")
    logger.info("=== review the above; re-run with --ingest to read + catalog ===")


def main() -> int:
    p = argparse.ArgumentParser(description="Build the evidence catalog from a Drive folder.")
    p.add_argument("listing", nargs="?", default="", help="'-' for stdin, or a lsjson file path.")
    p.add_argument("--remote", help="rclone remote (e.g. 'gdrive:') to list directly.")
    p.add_argument("--folder", help="folder under the remote (e.g. 'RRI Research').")
    p.add_argument("--dry-run", action="store_true",
                   help="Emit the review manifest (metadata only, reads NO bodies). Default.")
    p.add_argument("--ingest", action="store_true",
                   help="Read bodies and write evidence.db. Only after reviewing --dry-run.")
    p.add_argument("--db", help="evidence.db path (default: env / storage dir).")
    p.add_argument("--manifest-out", help="also write the dry-run manifest JSON here.")
    args = p.parse_args()

    conductor_email = os.environ.get("RRI_CONDUCTOR_EMAIL")
    entries = load_lsjson(args.listing, remote=args.remote, folder=args.folder)
    records = ev.plan_ingest(entries, conductor_email=conductor_email)

    if not args.ingest:  # default is the safe review path
        manifest = ev.build_manifest(records)
        print_manifest(manifest)
        if args.manifest_out:
            Path(args.manifest_out).write_text(json.dumps(manifest, indent=2))
            logger.info(f"manifest written to {args.manifest_out}")
        return 0

    # Real ingest — reads bodies. Requires a remote (or a custom reader).
    if not args.remote:
        raise SystemExit("--ingest needs --remote to read file bodies via rclone cat")
    conn = ev.connect(args.db)
    try:
        summary = ev.ingest_records(conn, records, _rclone_reader(args.remote))
        logger.info(f"ingest complete: {summary}")
        logger.info(f"catalog stats: {ev.stats(conn)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
