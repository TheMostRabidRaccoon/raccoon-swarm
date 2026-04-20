#!/usr/bin/env bash
# SessionEnd hook: flush per-pipeline journal drafts to their final destinations.
#
# For each draft at .claude/state/journal-draft-<pipeline>.md:
#   - Resolve the pipeline in .claude/skills/work-journal/pipelines.json
#   - Append the draft to journals/<pipeline>.md (always)
#   - If pipeline.local_only is false AND doc_id is set, emit a drive-sync
#     marker at .claude/state/pending-drive-sync-<pipeline>.md so the next
#     session can push to Google Docs via MCP
#   - If pipeline is unknown or local_only=true, never emit a drive-sync marker
#   - Delete the draft after a successful flush
#
# If no drafts exist, exit silently. "Task-completion-gated, not
# session-end-gated" — the hook only flushes what Claude intentionally wrote.
#
# DRY_RUN=1 prints actions without touching files — used by the privacy test.

set -euo pipefail

REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
STATE_DIR="$REPO_ROOT/.claude/state"
JOURNALS_DIR="$REPO_ROOT/journals"
PIPELINES_JSON="$REPO_ROOT/.claude/skills/work-journal/pipelines.json"
DRY_RUN="${DRY_RUN:-0}"

log() { echo "[journal-flush] $*" >&2; }

if [[ ! -f "$PIPELINES_JSON" ]]; then
  log "ERROR pipelines.json missing at $PIPELINES_JSON"
  log "ERROR drafts in $STATE_DIR will not be flushed until this is restored"
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  log "ERROR jq not found on PATH — cannot resolve pipelines.json"
  log "ERROR drafts in $STATE_DIR will be preserved for next session"
  log "ERROR install jq (brew install jq / apt-get install jq) to enable flushing"
  exit 1
fi

shopt -s nullglob
drafts=("$STATE_DIR"/journal-draft-*.md)
if [[ ${#drafts[@]} -eq 0 ]]; then
  exit 0
fi

mkdir -p "$JOURNALS_DIR"

for draft in "${drafts[@]}"; do
  name=$(basename "$draft" .md)
  pipeline="${name#journal-draft-}"

  if [[ ! -s "$draft" ]]; then
    log "draft for '$pipeline' is empty — skipping"
    [[ "$DRY_RUN" == "1" ]] || rm -f "$draft"
    continue
  fi

  # `// empty` would wrongly treat local_only=false as missing (jq's //
  # triggers on any falsy value), so check membership separately.
  known=$(jq -r --arg p "$pipeline" '.pipelines | has($p)' "$PIPELINES_JSON")
  if [[ "$known" != "true" ]]; then
    log "unknown pipeline '$pipeline' — leaving draft untouched"
    continue
  fi

  local_only=$(jq -r --arg p "$pipeline" '.pipelines[$p].local_only' "$PIPELINES_JSON")
  local_path=$(jq -r --arg p "$pipeline" '.pipelines[$p].local_path // empty' "$PIPELINES_JSON")
  doc_id=$(jq -r --arg p "$pipeline" '.pipelines[$p].doc_id // empty' "$PIPELINES_JSON")

  if [[ "$local_only" != "true" && "$local_only" != "false" ]]; then
    log "pipeline '$pipeline' has no boolean local_only flag — leaving draft untouched"
    continue
  fi

  target="$REPO_ROOT/$local_path"
  log "flush pipeline=$pipeline local_only=$local_only target=$target"

  if [[ "$DRY_RUN" == "1" ]]; then
    if [[ "$local_only" == "true" ]]; then
      log "DRY_RUN: would append to $target (LOCAL-ONLY, no drive marker)"
    elif [[ -n "$doc_id" ]]; then
      log "DRY_RUN: would append to $target AND emit drive-sync marker for doc_id=$doc_id"
    else
      log "DRY_RUN: would append to $target (work pipeline, but doc_id unset — no drive marker)"
    fi
    continue
  fi

  mkdir -p "$(dirname "$target")"
  cat "$draft" >> "$target"

  if [[ "$local_only" != "true" && -n "$doc_id" ]]; then
    marker="$STATE_DIR/pending-drive-sync-$pipeline.md"
    cat "$draft" >> "$marker"
    log "emitted drive-sync marker: $marker"
  fi

  rm -f "$draft"
done
