#!/usr/bin/env bash
# swarm-today — what did the swarm write in the last N hours?
#
# Usage:
#   ./scripts/swarm-today.sh           # last 24h
#   ./scripts/swarm-today.sh 6         # last 6 hours
#   SWARM_ROOT=/path ./scripts/swarm-today.sh
#
# Reads the filestore at $SWARM_ROOT (default ~/raccoon-swarm/swarm) and
# the OUTPUTS_DIR for synthesis DOCX files. Filesystem-only — no API
# calls, no auth required.

set -euo pipefail

SWARM_ROOT="${SWARM_ROOT:-$HOME/raccoon-swarm/swarm}"
HOURS="${1:-24}"
MMIN=$((HOURS * 60))

if [[ ! -d "$SWARM_ROOT" ]]; then
    echo "Error: swarm filestore not found at $SWARM_ROOT" >&2
    echo "Set SWARM_ROOT env var if your filestore lives elsewhere." >&2
    exit 1
fi

# Colors (NO_COLOR support, only when stdout is a TTY)
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); RESET=$(printf '\033[0m')
    TERRA=$(printf '\033[38;5;167m'); SAGE=$(printf '\033[38;5;108m')
else
    BOLD=""; DIM=""; RESET=""; TERRA=""; SAGE=""
fi

header() { printf "\n%s%s=== %s ===%s\n" "$BOLD" "$TERRA" "$1" "$RESET"; }
note()   { printf "  %s%s%s\n" "$DIM" "$1" "$RESET"; }

cd "$SWARM_ROOT"

printf "%s🦝 swarm-today%s — files written in the last %s%sh%s\n" \
    "$BOLD" "$RESET" "$BOLD" "$HOURS" "$RESET"
printf "%sfilestore: %s%s\n" "$DIM" "$SWARM_ROOT" "$RESET"

# ── 1. Persistence audit ──────────────────────────────────────────────
header "🪦 PERSISTENCE AUDIT"
latest_audit=$(find logs -maxdepth 1 -name "*persistence-audit*.md" -type f \
    -mmin "-$MMIN" 2>/dev/null | sort -r | head -1 || true)
if [[ -n "$latest_audit" ]]; then
    printf "  %s\n" "$latest_audit"
    counts=$(grep -E "^\s*-?\s*(triggers_identified|emails_sent|gap):" "$latest_audit" 2>/dev/null || true)
    judgment=$(grep -iE "respected mortality|live forever|judgment:" "$latest_audit" 2>/dev/null | head -1 || true)
    [[ -n "$counts" ]] && printf "%s\n" "$counts" | sed 's/^/    /'
    [[ -n "$judgment" ]] && printf "    %s\n" "$judgment"
    [[ -z "$counts$judgment" ]] && note "(no counts found — pre-postmaster-fix format)"
else
    note "(no audit written in last ${HOURS}h)"
fi

# ── 2. Positions + frameworks ────────────────────────────────────────
header "📌 POSITIONS + FRAMEWORKS (resolved decisions)"
positions=$(find positions frameworks -type f -mmin "-$MMIN" 2>/dev/null | sort || true)
if [[ -n "$positions" ]]; then
    printf "  %s\n" $positions
    printf "  %s%s total%s\n" "$DIM" "$(printf '%s\n' "$positions" | wc -l | tr -d ' ')" "$RESET"
else
    note "(none)"
fi

# ── 3. Artifacts (excluding code-runs scratch + images) ──────────────
header "📋 ARTIFACTS (scripts, plans, code)"
artifacts=$(find artifacts -type f -mmin "-$MMIN" \
    ! -path "*/code-runs/*" ! -path "*/images/*" 2>/dev/null | sort || true)
if [[ -n "$artifacts" ]]; then
    printf "  %s\n" $artifacts
    printf "  %s%s total%s\n" "$DIM" "$(printf '%s\n' "$artifacts" | wc -l | tr -d ' ')" "$RESET"
else
    note "(none)"
fi

# ── 4. Images with model attribution ─────────────────────────────────
header "🖼  IMAGES (with model attribution)"
images=$(find artifacts/images -type f -mmin "-$MMIN" 2>/dev/null | sort || true)
if [[ -n "$images" ]]; then
    img_count=$(printf '%s\n' "$images" | wc -l | tr -d ' ')
    printf "  %s%s images generated%s\n" "$SAGE" "$img_count" "$RESET"
    while IFS= read -r imgpath; do
        base=$(basename "$imgpath")
        model="?"
        if [[ -f logs/image-generations.log ]]; then
            model=$(grep -F "$base" logs/image-generations.log 2>/dev/null \
                | tail -1 | grep -oE "model=[a-z_]+" | cut -d= -f2 || true)
            [[ -z "$model" ]] && model="?"
        fi
        printf "  %s  %s(%s)%s\n" "$imgpath" "$DIM" "$model" "$RESET"
    done <<< "$images"
else
    note "(none)"
fi

# ── 5. Open: questions, pursuits, tasks ──────────────────────────────
header "❓ OPEN: questions, pursuits, tasks"
opens=$(find questions pursuits tasks -type f -mmin "-$MMIN" 2>/dev/null | sort || true)
if [[ -n "$opens" ]]; then
    printf "  %s\n" $opens
else
    note "(none)"
fi

# ── 6. Other logs (the audit is shown above) ─────────────────────────
header "📜 OTHER LOGS"
other_logs=$(find logs -maxdepth 1 -type f -mmin "-$MMIN" \
    ! -name "*persistence-audit*" 2>/dev/null | sort || true)
if [[ -n "$other_logs" ]]; then
    printf "  %s\n" $other_logs
else
    note "(none)"
fi

# ── 7. Session synthesis DOCX (outside filestore) ────────────────────
header "📄 SESSION SYNTHESIS DOCX"
docs=$(find "$HOME/raccoon-swarm" -maxdepth 4 -name "loop_synthesis_*.docx" \
    -mmin "-$MMIN" -type f 2>/dev/null | sort -r || true)
if [[ -n "$docs" ]]; then
    printf "  %s\n" $docs
else
    note "(none)"
fi

printf "\n%sTip: pass an hours arg, e.g. './scripts/swarm-today.sh 6' for last 6 hours.%s\n" "$DIM" "$RESET"
