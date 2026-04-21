#!/usr/bin/env bash
# PostToolUse hook on Bash: after a successful `git push`, diff the pushed
# commits and surface which docs/stack/*.md files need refreshing.
#
# The hook reads PostToolUse JSON on stdin:
#   { "tool_name": "Bash", "tool_input": {"command": "..."}, "tool_response": {...}, ... }
#
# It ONLY acts when tool_input.command looks like a `git push`. All other
# Bash commands exit 0 silently.
#
# The hook does not edit any file. It prints a banner to stdout listing
# docs/stack/*.md slices whose source-of-truth files were touched in the
# pushed range. Claude reads the banner and opens a follow-up commit.
#
# Diff range: range = @{push}..HEAD if the branch has an upstream, else
# main..HEAD as a fallback so the first push still reports something useful.
#
# Mapping (path glob → doc slice) lives inline below — keep it in sync with
# docs/stack/README.md.
#
# Exits 0 on all normal paths, including: not a push, jq missing, no stack
# impact. Exits 0 on diff errors too — this is a nudge, not a gate.

set -uo pipefail

REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$REPO_ROOT" 2>/dev/null || exit 0

say() { echo "$*"; }
log() { echo "[stack-doc-nudge] $*" >&2; }

# Read the PostToolUse payload. If jq is missing or stdin isn't JSON, bail
# quietly — the hook is advisory, never blocking.
payload="$(cat 2>/dev/null || true)"
[[ -z "$payload" ]] && exit 0

if ! command -v jq >/dev/null 2>&1; then
  log "jq missing — skipping stack-doc nudge"
  exit 0
fi

tool_name=$(printf '%s' "$payload" | jq -r '.tool_name // empty' 2>/dev/null || true)
[[ "$tool_name" != "Bash" ]] && exit 0

cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
[[ -z "$cmd" ]] && exit 0

# Match `git push` anywhere in the command (handles `git push -u origin foo`,
# `git -C path push`, chained `&&` commands, etc). Avoid false positives on
# strings like `# git push later` by requiring `git` as a token before push.
if ! printf '%s' "$cmd" | grep -Eq '(^|[[:space:];&|])git([[:space:]]+-[^[:space:]]+)*[[:space:]]+push([[:space:]]|$)'; then
  exit 0
fi

# Pick a diff range. Prefer the upstream's prior tip (@{push}), which points
# at the remote ref before this push. If unavailable (first push, detached
# head, etc.), fall back to origin/main..HEAD, then main..HEAD.
range=""
if git rev-parse --verify --quiet '@{push}' >/dev/null 2>&1; then
  range='@{push}..HEAD'
elif git rev-parse --verify --quiet 'origin/main' >/dev/null 2>&1; then
  range='origin/main..HEAD'
elif git rev-parse --verify --quiet 'main' >/dev/null 2>&1; then
  range='main..HEAD'
else
  log "no diff base available — skipping"
  exit 0
fi

mapfile -t changed < <(git diff --name-only "$range" 2>/dev/null || true)
if [[ ${#changed[@]} -eq 0 ]]; then
  exit 0
fi

# path→doc mapping. Order matters: first match wins per file.
# Keep in sync with docs/stack/README.md "Source of truth" blocks.
declare -A impact=()
note_impact() {
  local doc="$1" reason="$2"
  if [[ -z "${impact[$doc]:-}" ]]; then
    impact[$doc]="$reason"
  else
    impact[$doc]="${impact[$doc]}, $reason"
  fi
}

for f in "${changed[@]}"; do
  case "$f" in
    requirements.txt|runtime.txt|Procfile)
      note_impact "runtime.md" "$f"
      ;;
    .env.example)
      # env vars cross-cut — flag deploy + auth + models
      note_impact "deploy.md" "$f"
      note_impact "auth.md" "$f"
      note_impact "models.md" "$f"
      ;;
    .github/workflows/*)
      note_impact "ci.md" "$f"
      ;;
    .claude/hooks/*|.claude/settings.json|.claude/skills/*)
      note_impact "hooks.md" "$f"
      ;;
    raccoon_swarm_server.py)
      # The server file is the source of truth for several slices. Without
      # parsing the diff, nudge all slices that mirror it so Claude can
      # decide which actually need a refresh.
      note_impact "runtime.md" "server edits"
      note_impact "models.md" "server edits"
      note_impact "storage.md" "server edits"
      note_impact "auth.md" "server edits"
      ;;
    README.md)
      note_impact "models.md" "README roster/tech stack"
      note_impact "deploy.md" "README deploy section"
      ;;
    docs/stack/*)
      # Edits to the stack docs themselves are the refresh — no nudge needed.
      :
      ;;
  esac
done

if [[ ${#impact[@]} -eq 0 ]]; then
  exit 0
fi

say "=== stack-docs: refresh suggested ==="
say "Pushed range: $range"
say "The files below changed and feed the listed stack docs. Re-read each"
say "source-of-truth block and update the doc if anything drifted."
say ""
for doc in "${!impact[@]}"; do
  say "  - docs/stack/$doc  ← ${impact[$doc]}"
done
say ""
say "If nothing semantically changed (e.g. a pure formatting edit), skip."
say "Open a follow-up commit titled 'docs(stack): refresh <slice>' per doc."
say "======================================"

exit 0
