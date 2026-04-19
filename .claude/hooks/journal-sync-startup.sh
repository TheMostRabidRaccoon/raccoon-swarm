#!/usr/bin/env bash
# SessionStart hook: surface pending work-journal drive-syncs to Claude.
#
# The SessionEnd flush hook writes pending-drive-sync-<pipeline>.md markers
# for every non-personal pipeline with a doc_id. This hook scans for those
# markers at the start of each session and emits a structured banner telling
# Claude to drain them by pushing each marker's content to its Google Doc
# via the MCP tool, then deleting the marker.
#
# Hooks are bash — they can't call MCP tools themselves. Claude does that.
# This hook's only job is to make the pending work visible.
#
# Defense-in-depth: if a pending-drive-sync-personal.md ever appears (it
# shouldn't — the flush hook refuses to emit one), this hook exits NON-ZERO
# with a loud error so the session surfaces the violation. The marker is
# NOT deleted — preserved as evidence for the user to inspect.
#
# Exits 0 on normal operation (including when no markers exist).

set -euo pipefail

REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
STATE_DIR="$REPO_ROOT/.claude/state"
PIPELINES_JSON="$REPO_ROOT/.claude/skills/work-journal/pipelines.json"

# Stdout reaches Claude as session context. Stderr is harness-visible only.
say() { echo "$*"; }
log() { echo "[journal-sync-startup] $*" >&2; }

if [[ ! -d "$STATE_DIR" ]]; then
  exit 0
fi

shopt -s nullglob
markers=("$STATE_DIR"/pending-drive-sync-*.md)
if [[ ${#markers[@]} -eq 0 ]]; then
  exit 0
fi

# --- Defense-in-depth: personal pipeline must never have a pending marker ---
personal_marker="$STATE_DIR/pending-drive-sync-personal.md"
if [[ -f "$personal_marker" ]]; then
  say "=== WORK-JOURNAL PRIVACY VIOLATION ==="
  say "A pending-drive-sync marker exists for the 'personal' pipeline."
  say "This pipeline is local-only and MUST NEVER be synced to Google Drive."
  say ""
  say "Marker preserved at: $personal_marker"
  say ""
  say "REQUIRED ACTIONS (do these BEFORE any other work this session):"
  say "  1. Tell the user immediately and surface the marker contents."
  say "  2. Do NOT call any Google Docs / Drive MCP tool with this content."
  say "  3. Investigate how the marker was created (flush-hook bug?"
  say "     pipelines.json tampering? manual creation?)."
  say "  4. Only delete the marker after the user has confirmed review."
  say "====================================="
  log "FATAL: pending-drive-sync-personal.md exists — preserving and failing"
  exit 1
fi

# --- Normal path: list pending syncs with doc_ids for Claude to process ---
if ! command -v jq >/dev/null 2>&1; then
  say "[work-journal] Pending drive-sync markers exist but jq is not installed."
  say "Install jq to enable automated Doc lookup, or push markers manually."
  for m in "${markers[@]}"; do
    say "  - $m"
  done
  exit 0
fi

if [[ ! -f "$PIPELINES_JSON" ]]; then
  say "[work-journal] Pending drive-sync markers exist but pipelines.json is missing."
  for m in "${markers[@]}"; do
    say "  - $m"
  done
  exit 0
fi

say "=== work-journal: pending drive-syncs ==="
say "The SessionEnd flush hook wrote the markers below. Drain them now:"
say ""
say "For each pending pipeline:"
say "  1. Read the marker file to get the entry content."
say "  2. Append it to the Google Doc (doc_id listed) using the Google Docs"
say "     MCP append tool. If that tool is not available, tell the user once"
say "     ('Google Docs MCP not detected — markers left for next session')"
say "     and STOP — do not delete any markers."
say "  3. On successful append, delete the marker file."
say "  4. If an append fails, leave the marker and report the error to the user."
say ""
say "Pending:"

had_unknown=0
for marker in "${markers[@]}"; do
  name=$(basename "$marker" .md)
  pipeline="${name#pending-drive-sync-}"

  known=$(jq -r --arg p "$pipeline" '.pipelines | has($p)' "$PIPELINES_JSON")
  if [[ "$known" != "true" ]]; then
    say "  - $pipeline → UNKNOWN pipeline (not in pipelines.json) ← $marker"
    had_unknown=1
    continue
  fi

  local_only=$(jq -r --arg p "$pipeline" '.pipelines[$p].local_only' "$PIPELINES_JSON")
  doc_id=$(jq -r --arg p "$pipeline" '.pipelines[$p].doc_id // empty' "$PIPELINES_JSON")

  if [[ "$local_only" == "true" ]]; then
    # Should have been caught by the personal check above, but handle any
    # other future local_only pipelines too.
    say "  - $pipeline → local_only=true (MARKER SHOULD NOT EXIST) ← $marker"
    log "FATAL: pending marker for local_only pipeline '$pipeline' — preserving and failing"
    exit 1
  fi

  if [[ -z "$doc_id" ]]; then
    say "  - $pipeline → NO doc_id configured (set it in pipelines.json before draining) ← $marker"
    had_unknown=1
    continue
  fi

  say "  - $pipeline → doc_id=$doc_id ← $marker"
done

say "========================================="

if [[ "$had_unknown" == "1" ]]; then
  log "some markers could not be resolved to a doc_id — see banner"
fi

exit 0
