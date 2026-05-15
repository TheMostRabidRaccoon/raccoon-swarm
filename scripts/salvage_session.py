#!/usr/bin/env python3
# ruff: noqa: E402
"""salvage_session — post-hoc completion for tool-loop-truncated responses.

Reads a saved session JSON (raccoon_loop_*.json), finds any model output that
ended with a truncation marker, and uses Claude Haiku to generate a 200-word
closing paragraph synthesizing the model's apparent conclusion from its
partial reasoning. Appends the salvage to the original output, annotated so
readers know it's a post-hoc completion not the model's own closing.

This is the reactive sibling to the in-loop wind-down warnings in
swarm_orchestrator.py — the wind-down prevents most truncations proactively;
the salvage cleans up the rest.

Usage:
  ./scripts/salvage_session.py path/to/raccoon_loop_*.json
  ./scripts/salvage_session.py --inplace path/to/raccoon_loop_*.json
  ./scripts/salvage_session.py --dry-run path/to/raccoon_loop_*.json

Default output: writes a new file alongside the input with .salvaged.json
extension, leaving the original untouched. --inplace overwrites the original.
--dry-run prints what WOULD be salvaged without making API calls.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VENV_PYTHON = _REPO_ROOT / "venv" / "bin" / "python3"
if _VENV_PYTHON.exists() and Path(sys.executable).resolve() != _VENV_PYTHON.resolve():
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), __file__, *sys.argv[1:]])

import argparse  # noqa: E402
import json  # noqa: E402

sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

import swarm_orchestrator  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("session_json", type=Path, help="Path to a raccoon_loop_*.json file")
    p.add_argument("--inplace", action="store_true",
                   help="Overwrite the original file. Default writes <name>.salvaged.json next to it.")
    p.add_argument("--dry-run", action="store_true",
                   help="List what would be salvaged; don't call any APIs or write any files.")
    args = p.parse_args()

    if not args.session_json.exists():
        print(f"error: {args.session_json} not found", file=sys.stderr)
        return 2

    data = json.loads(args.session_json.read_text())
    query = data.get("query", "")
    rounds = data.get("rounds", [])
    if not rounds:
        print("session has no rounds; nothing to salvage")
        return 0

    print(f"🦝 salvage_session — {args.session_json}")
    print(f"   {len(rounds)} round(s); scanning for truncations")

    total_truncated = 0
    total_salvaged = 0

    for round_idx, round_results in enumerate(rounds):
        truncations = swarm_orchestrator.detect_truncations(round_results)
        if not truncations:
            continue
        print(f"   round {round_idx + 1}: {len(truncations)} truncation(s)")
        total_truncated += len(truncations)

        for model_name, partial_text in truncations:
            print(f"     • {model_name} ({len(partial_text)} chars)")
            if args.dry_run:
                continue
            salvage = swarm_orchestrator.salvage_truncated_response(
                model_name=model_name,
                partial_text=partial_text,
                original_query=query,
            )
            if not salvage:
                print(f"       salvage failed (see logs)")
                continue
            # Append the salvage to the original truncated text
            round_results[model_name] = partial_text + "\n\n" + salvage
            total_salvaged += 1
            print(f"       salvaged: {len(salvage)} chars appended")

    if args.dry_run:
        print(f"\ndry-run: would salvage {total_truncated} truncation(s); no files written.")
        return 0

    if total_salvaged == 0:
        print(f"\nno salvageable truncations; no files written.")
        return 0

    out_path = args.session_json if args.inplace else args.session_json.with_suffix(".salvaged.json")
    out_path.write_text(json.dumps(data, indent=2, default=str))
    print(f"\nwrote {out_path} — {total_salvaged}/{total_truncated} truncations salvaged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
