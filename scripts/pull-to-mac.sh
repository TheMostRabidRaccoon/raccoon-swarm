#!/usr/bin/env bash
# pull-to-mac — snapshot today's swarm output from the Linux server to your Mac.
#
# Run this ON YOUR MAC. It rsyncs new .md / .docx / .png files (skipping code-run
# scratch) from the swarm server to ~/Downloads/swarm-YYYYMMDD/.
#
# Usage:
#   ./scripts/pull-to-mac.sh                           # defaults: today's date, all files
#   ./scripts/pull-to-mac.sh ~/Desktop/swarm-snapshot  # custom destination
#
# Configuration (env vars):
#   SWARM_HOST      remote host (default: 192.168.1.174)
#   SWARM_USER      remote user (default: theconductor)
#   SWARM_REMOTE    remote raccoon-swarm path (default: ~/raccoon-swarm)
#
# Examples:
#   SWARM_HOST=raccoon-swarm.local ./scripts/pull-to-mac.sh
#   ./scripts/pull-to-mac.sh ~/Drive/SwarmArchive/$(date +%Y-%m-%d)
#
# Idempotent: re-run anytime; only changed files transfer. Skips code_exec
# scratch and tmp.

set -euo pipefail

SWARM_HOST="${SWARM_HOST:-192.168.1.174}"
SWARM_USER="${SWARM_USER:-theconductor}"
SWARM_REMOTE="${SWARM_REMOTE:-~/raccoon-swarm}"
DEST="${1:-$HOME/Downloads/swarm-$(date +%Y%m%d)}"

REMOTE="${SWARM_USER}@${SWARM_HOST}"

# Colors (NO_COLOR support)
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); RESET=$(printf '\033[0m')
    SAGE=$(printf '\033[38;5;108m'); TERRA=$(printf '\033[38;5;167m')
else
    BOLD=""; DIM=""; RESET=""; SAGE=""; TERRA=""
fi

printf "%s🦝 pull-to-mac%s\n" "$BOLD" "$RESET"
printf "  %sfrom:%s %s:%s\n" "$DIM" "$RESET" "$REMOTE" "$SWARM_REMOTE"
printf "  %sto:  %s%s\n\n" "$DIM" "$RESET" "$DEST"

mkdir -p "$DEST/swarm" "$DEST/outputs"

# ── Filestore: .md + .png, skip code-runs scratch ────────────────────
printf "%s== filestore (md / png, skipping code-runs) ==%s\n" "$TERRA" "$RESET"
rsync -avz --human-readable \
    --include='*/' \
    --include='*.md' \
    --include='*.png' \
    --include='*.log' \
    --exclude='code-runs/***' \
    --exclude='*' \
    "${REMOTE}:${SWARM_REMOTE}/swarm/" \
    "$DEST/swarm/" \
    || { printf "\n%srsync of /swarm/ failed%s\n" "$TERRA" "$RESET"; exit 1; }

# ── Outputs: synthesis DOCX files ───────────────────────────────────
printf "\n%s== outputs (loop synthesis DOCX) ==%s\n" "$TERRA" "$RESET"
# OUTPUTS_DIR is usually $SWARM_REMOTE/outputs but the swarm may also keep
# DOCX files at $SWARM_REMOTE/. Pull both paths if present.
rsync -avz --human-readable \
    --include='loop_synthesis_*.docx' \
    --include='*/' \
    --exclude='*' \
    "${REMOTE}:${SWARM_REMOTE}/" \
    "$DEST/outputs/" \
    2>/dev/null || true

printf "\n%s✓ done%s — %s%s%s\n" "$SAGE" "$RESET" "$BOLD" "$DEST" "$RESET"

# Quick summary of what landed
md_count=$(find "$DEST/swarm" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
png_count=$(find "$DEST/swarm" -name '*.png' 2>/dev/null | wc -l | tr -d ' ')
log_count=$(find "$DEST/swarm" -name '*.log' 2>/dev/null | wc -l | tr -d ' ')
docx_count=$(find "$DEST/outputs" -name 'loop_synthesis_*.docx' 2>/dev/null | wc -l | tr -d ' ')
printf "  %s md  /  %s png  /  %s log  /  %s docx\n" \
    "$md_count" "$png_count" "$log_count" "$docx_count"
