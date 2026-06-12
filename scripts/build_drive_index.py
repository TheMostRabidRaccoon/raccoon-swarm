#!/usr/bin/env python3
"""Build the external Drive index manifest the swarm reads at boot.

The swarm can only "see" its own filestore. Artifacts saved to Google Drive
(e.g. a finished script) are invisible to it, so it concludes they are lost and
burns rounds reconstructing them. This script writes a small manifest of Drive
filenames that swarm_filestore.drive_index_context() surfaces into round 1.

Input: `rclone lsjson` output (the easiest auth-light way to list a Drive).
  - Configure an rclone remote once (`rclone config`), then either:
      rclone lsjson gdrive: --recursive | scripts/build_drive_index.py -
  - or let this script run rclone for you:
      scripts/build_drive_index.py --remote gdrive: --recursive

Output: JSON manifest (default <storage>/swarm/_drive_index.json, overridable
with RRI_DRIVE_INDEX or --out). Re-run on a cron/timer to keep it fresh.

This is intentionally a thin starter — swap rclone for the Drive API or `gdrive`
if you prefer; the only contract is the output schema:
  [{"name": str, "url": str|null, "modified": str|null}, ...]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _default_out() -> Path:
    env = os.getenv("RRI_DRIVE_INDEX")
    if env:
        return Path(env)
    base = os.getenv("RRI_STORAGE_DIR")
    root = (Path(base) / "swarm") if base else (Path(".") / "swarm")
    return root / "_drive_index.json"


def _load_rclone_json(args: argparse.Namespace) -> list[dict]:
    """Read `rclone lsjson` entries from a file/stdin or by invoking rclone."""
    if args.source == "-":
        raw = sys.stdin.read()
    elif args.source:
        raw = Path(args.source).read_text(encoding="utf-8")
    elif args.remote:
        cmd = ["rclone", "lsjson", args.remote]
        if args.recursive:
            cmd.append("--recursive")
        raw = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    else:
        raise SystemExit("provide a SOURCE file/'-', or --remote to run rclone")
    return json.loads(raw)


def _to_manifest(entries: list[dict]) -> list[dict]:
    out = []
    for e in entries:
        if e.get("IsDir"):
            continue
        out.append({
            "name": e.get("Path") or e.get("Name") or "?",
            # rclone lsjson includes an ID; build a Drive open link when present.
            "url": (f"https://drive.google.com/open?id={e['ID']}" if e.get("ID") else None),
            "modified": e.get("ModTime"),
        })
    out.sort(key=lambda x: x.get("modified") or "", reverse=True)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", nargs="?", help="rclone lsjson output file, or '-' for stdin")
    p.add_argument("--remote", help="rclone remote to list (e.g. 'gdrive:'), runs rclone for you")
    p.add_argument("--recursive", action="store_true", help="recurse into subfolders")
    p.add_argument("--out", type=Path, default=_default_out(), help="manifest output path")
    args = p.parse_args()

    entries = _load_rclone_json(args)
    manifest = _to_manifest(entries)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {len(manifest)} Drive entries -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
