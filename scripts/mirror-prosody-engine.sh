#!/usr/bin/env bash
# Mirror the prosody-intelligence src/ tree into the swarm filestore so
# any model can read the pipeline source on demand via filestore_search /
# filestore_read. Run this manually after a prosody-intelligence change,
# or hook it into a cron / pre-dispatch step if you want it always fresh.
#
# Resolves the swarm filestore root the same way swarm_filestore does:
#   - $RRI_STORAGE_DIR/swarm/  if set
#   - ./swarm/                  otherwise
#
# Override the source repo via PROSODY_SRC_DIR if your checkout lives
# somewhere other than ../prosody-intelligence.

set -euo pipefail

PROSODY_SRC_DIR="${PROSODY_SRC_DIR:-$HOME/prosody-intelligence/src}"
DEST_BASE="${RRI_STORAGE_DIR:-$(pwd)}/swarm/artifacts/prosody-engine"

if [[ ! -d "$PROSODY_SRC_DIR" ]]; then
  echo "error: PROSODY_SRC_DIR=$PROSODY_SRC_DIR does not exist" >&2
  echo "set PROSODY_SRC_DIR to your prosody-intelligence/src checkout" >&2
  exit 1
fi

mkdir -p "$DEST_BASE"

rsync -av --delete \
  --include='*.py' \
  --include='*.md' \
  --include='*/' \
  --exclude='*' \
  "$PROSODY_SRC_DIR/" "$DEST_BASE/"

# Drop a README that orients models. Overwritten on every mirror.
cat > "$DEST_BASE/_README.md" <<'EOF'
# prosody-engine (mirror of prosody-intelligence/src/)

This directory is a read-only mirror of the Prosody Intelligence
pipeline source so any model in the swarm can `filestore_read` it on
demand. Updated by `scripts/mirror-prosody-engine.sh`.

## Files

- `app.py` — Flask API + UI surface.
- `prosody_pipeline.py` — Forward pipeline (audio → transcript +
  acoustic features → LLM analysis).
- `reverse_pipeline.py` — Reverse pipeline (text → emotion-tagged →
  ElevenLabs TTS, with the 14-emotion palette + parameter map).
- `calibration.py` — Layer 5.5: runs generated audio back through the
  forward pipeline, measures deltas vs. expected acoustic signatures,
  produces tuning recommendations.
- `compositor.py` — Layer 6: stills + audio + emotion map → MP4 with
  Ken Burns motion and emotion-colored subtitles.
- `session_director.py` — End-to-end automation (document → script →
  audio → video).

## Usage from the swarm

`filestore_search("emotion params")` → finds `reverse_pipeline.py`.
`filestore_read("artifacts/prosody-engine/reverse_pipeline.py")` →
returns full source.

DO NOT modify files in this directory from inside the swarm — they're
overwritten on every mirror. Make changes in the prosody-intelligence
repo and re-run the mirror script.
EOF

echo "mirrored $(find "$DEST_BASE" -name '*.py' | wc -l) .py files into $DEST_BASE"
