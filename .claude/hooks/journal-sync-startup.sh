#!/usr/bin/env bash
# SessionStart hook: surface pending work-journal drive-syncs and degraded
# environments to Claude.
#
# The SessionEnd flush hook writes pending-drive-sync-<pipeline>.md markers
# for every non-personal pipeline with a doc_id. This hook scans for those
# markers at the start of each session and emits a structured banner telling
# Claude to drain them by pushing each marker's content to its Google Doc
# via the MCP tool, then deleting the marker.
#
# Hooks are bash — they can't call MCP tools themselves. Claude does that.
# This hook's only job is to make the pending work visible, and to loudly
# flag degraded states that would otherwise let drafts rot silently.
#
# Degraded-state banners surfaced to Claude:
#   - jq missing: neither this hook nor the flush hook can operate
#   - pipelines.json missing: drafts and markers can't be resolved
#   - stale drafts: any .claude/state/journal-draft-*.md older than 24h
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
drafts=("$STATE_DIR"/journal-draft-*.md)

# Stale drafts = journal entries written in a prior session that never got
# flushed (e.g. jq was missing at SessionEnd, or the session crashed before
# the hook fired). Surface these so work doesn't silently rot.
stale_drafts=()
if [[ ${#drafts[@]} -gt 0 ]]; then
  while IFS= read -r -d '' f; do
    stale_drafts+=("$f")
  done < <(find "$STATE_DIR" -maxdepth 1 -name 'journal-draft-*.md' -type f -mtime +1 -print0 2>/dev/null)
fi

# Stale markers = drive-sync markers that haven't been drained in >7 days.
# Causes: MCP was unavailable for weeks, user never returned to that
# pipeline, or the drain flow is silently broken. Threshold is looser
# than for drafts because markers are normal to sit a few days.
stale_markers=()
if [[ ${#markers[@]} -gt 0 ]]; then
  while IFS= read -r -d '' f; do
    stale_markers+=("$f")
  done < <(find "$STATE_DIR" -maxdepth 1 -name 'pending-drive-sync-*.md' -type f -mtime +7 -print0 2>/dev/null)
fi

# Nothing to report
if [[ ${#markers[@]} -eq 0 && ${#stale_drafts[@]} -eq 0 ]]; then
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

# --- Degraded env: jq missing ---
if ! command -v jq >/dev/null 2>&1; then
  say "=== work-journal: DEGRADED (jq missing) ==="
  say "jq is not installed, so the flush and sync hooks cannot parse"
  say "pipelines.json. Drafts and markers will accumulate until jq is"
  say "installed. On Mac: brew install jq. On Linux: apt-get install jq."
  say ""
  if [[ ${#markers[@]} -gt 0 ]]; then
    say "Pending drive-sync markers (${#markers[@]}):"
    for m in "${markers[@]}"; do say "  - $m"; done
  fi
  if [[ ${#stale_drafts[@]} -gt 0 ]]; then
    say "Stale drafts older than 24h (${#stale_drafts[@]}):"
    for d in "${stale_drafts[@]}"; do say "  - $d"; done
  fi
  say "==========================================="
  log "WARN: jq missing — flagged to Claude"
  exit 0
fi

# --- Degraded env: pipelines.json missing ---
if [[ ! -f "$PIPELINES_JSON" ]]; then
  say "=== work-journal: DEGRADED (pipelines.json missing) ==="
  say "pipelines.json is missing at $PIPELINES_JSON — hooks can't resolve"
  say "doc_ids or local_only flags. Restore it before draining."
  say ""
  if [[ ${#markers[@]} -gt 0 ]]; then
    say "Pending drive-sync markers (${#markers[@]}):"
    for m in "${markers[@]}"; do say "  - $m"; done
  fi
  say "======================================================"
  log "WARN: pipelines.json missing — flagged to Claude"
  exit 0
fi

# --- Stale drafts (may coexist with normal markers) ---
if [[ ${#stale_drafts[@]} -gt 0 ]]; then
  say "=== work-journal: stale drafts (>24h old) ==="
  say "These drafts were written in a prior session but never flushed."
  say "Most likely the session crashed or SessionEnd hook didn't fire."
  say "Consider: review the content, then either move it into a fresh"
  say "draft for a current pipeline or delete it to clear the backlog."
  say ""
  for d in "${stale_drafts[@]}"; do say "  - $d"; done
  say "=============================================="
fi

# --- Stale markers (drain has been blocked for >7 days) ---
if [[ ${#stale_markers[@]} -gt 0 ]]; then
  say "=== work-journal: stale drive-sync markers (>7 days old) ==="
  say "These markers should have been drained to Google Docs but haven't."
  say "Causes: MCP unavailable for weeks, drain flow silently failing,"
  say "or you haven't had a session since they were written."
  say "Investigate before draining — something is likely wrong."
  say ""
  for m in "${stale_markers[@]}"; do say "  - $m"; done
  say "============================================================"
fi

# --- Normal path: list pending syncs with doc_ids for Claude to process ---
if [[ ${#markers[@]} -eq 0 ]]; then
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
