#!/usr/bin/env bash
# BLOCKING TEST: the personal journal must never emit a drive-sync marker,
# and every pipeline in config must declare local_only explicitly.
#
# Iterates every pipeline found in pipelines.json (not a hardcoded list), so
# a newly-added pipeline that forgets to set local_only is caught. Seeds one
# draft per pipeline and runs the flush hook in DRY_RUN mode, asserting:
#   1. Every pipeline has a boolean local_only (not null/missing).
#   2. The personal pipeline is local_only=true and doc_id=null.
#   3. DRY_RUN output emits NO drive-sync marker for ANY local_only=true
#      pipeline, even with a poisoned doc_id.
#   4. DRY_RUN output logs a flush line for every pipeline with a draft.
#
# Runs in a sandboxed temp tree — does not touch real journals or state.
# Exit 0 = safe. Non-zero = privacy leak, do not merge.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PIPELINES_JSON="$REPO_ROOT/.claude/skills/work-journal/pipelines.json"
HOOK="$REPO_ROOT/.claude/hooks/journal-flush.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

command -v jq >/dev/null || fail "jq required for this test"
[[ -f "$PIPELINES_JSON" ]] || fail "pipelines.json missing at $PIPELINES_JSON"
[[ -x "$HOOK" ]] || fail "flush hook not executable: $HOOK"

# ---------- Assertion 1: every pipeline declares a boolean local_only ----------
pipelines=()
while IFS= read -r p; do pipelines+=("$p"); done < <(jq -r '.pipelines | keys[]' "$PIPELINES_JSON")
[[ ${#pipelines[@]} -gt 0 ]] || fail "no pipelines defined in $PIPELINES_JSON"

for p in "${pipelines[@]}"; do
  flag=$(jq -r --arg p "$p" '.pipelines[$p].local_only' "$PIPELINES_JSON")
  if [[ "$flag" != "true" && "$flag" != "false" ]]; then
    fail "$p.local_only must be a boolean, got: $flag — every pipeline needs an explicit privacy decision"
  fi
  pass "$p.local_only=$flag (explicit)"
done

# ---------- Assertion 2: personal invariant ----------
[[ "$(jq -r '.pipelines.personal.local_only' "$PIPELINES_JSON")" == "true" ]] \
  || fail "personal.local_only must be true"
[[ "$(jq -r '.pipelines.personal.doc_id // "null"' "$PIPELINES_JSON")" == "null" ]] \
  || fail "personal.doc_id must be null"
pass "personal is local_only=true, doc_id=null"

# ---------- Sandbox: seed drafts for every pipeline, run DRY_RUN ----------
SANDBOX=$(mktemp -d)
trap 'rm -rf "$SANDBOX"' EXIT

mkdir -p "$SANDBOX/.claude/state" "$SANDBOX/.claude/skills/work-journal" "$SANDBOX/.claude/hooks" "$SANDBOX/journals"
cp "$HOOK" "$SANDBOX/.claude/hooks/journal-flush.sh"
chmod +x "$SANDBOX/.claude/hooks/journal-flush.sh"

# Poison: set a bogus doc_id on every local_only=true pipeline so the test
# proves local_only wins over doc_id presence. Also set test doc_ids on every
# work pipeline so we can verify markers DO appear for them.
jq '
  .pipelines |= with_entries(
    if .value.local_only == true then
      .value.doc_id = "MUST_NEVER_BE_USED_\(.key)"
    else
      .value.doc_id = "TEST_DOC_ID_\(.key)"
    end
  )
' "$PIPELINES_JSON" > "$SANDBOX/.claude/skills/work-journal/pipelines.json"

for p in "${pipelines[@]}"; do
  printf '## 2026-04-19 00:00 — privacy test entry for %s\n\n**Kind:** discovered\n**Pipeline:** %s\n\nSeeded content. Must never reach Drive if local_only=true.\n\n---\n' \
    "$p" "$p" > "$SANDBOX/.claude/state/journal-draft-$p.md"
done

output=$(CLAUDE_PROJECT_DIR="$SANDBOX" DRY_RUN=1 bash "$SANDBOX/.claude/hooks/journal-flush.sh" 2>&1)

echo "--- hook DRY_RUN output ---"
echo "$output"
echo "---------------------------"

# ---------- Assertion 3: no drive-sync marker for ANY local_only=true pipeline ----------
for p in "${pipelines[@]}"; do
  flag=$(jq -r --arg p "$p" '.pipelines[$p].local_only' "$SANDBOX/.claude/skills/work-journal/pipelines.json")
  if [[ "$flag" == "true" ]]; then
    if echo "$output" | grep -E "drive-sync marker for doc_id=MUST_NEVER_BE_USED_$p" >/dev/null; then
      fail "local_only pipeline '$p' would have emitted a drive-sync marker — PRIVACY LEAK"
    fi
    if ! echo "$output" | grep -E "would append to .*/journals/$p.md \(LOCAL-ONLY" >/dev/null; then
      fail "local_only pipeline '$p' did not emit expected LOCAL-ONLY log line"
    fi
    pass "$p (local_only=true) logged LOCAL-ONLY, no marker"
  else
    if ! echo "$output" | grep -E "AND emit drive-sync marker for doc_id=TEST_DOC_ID_$p" >/dev/null; then
      fail "work pipeline '$p' did not emit drive-sync marker — flush routing broken"
    fi
    pass "$p (local_only=false) emits drive-sync marker as expected"
  fi
done

# ---------- Assertion 4: every pipeline was processed ----------
for p in "${pipelines[@]}"; do
  echo "$output" | grep -E "pipeline=$p " >/dev/null \
    || fail "hook did not process pipeline '$p'"
done
pass "all ${#pipelines[@]} pipelines processed"

echo
echo "ALL PRIVACY CHECKS PASSED"
