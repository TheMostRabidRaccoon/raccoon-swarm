#!/usr/bin/env bash
# BLOCKING TEST: the personal journal must never emit a drive-sync marker.
#
# Seeds one draft per pipeline, runs the flush hook in DRY_RUN mode, and
# asserts:
#   1. The personal pipeline is flagged local_only=true in pipelines.json
#   2. DRY_RUN output does NOT contain a drive-sync action for personal
#   3. Every work pipeline is flagged local_only=false
#
# Exit 0 = safe. Non-zero = privacy leak, do not merge.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PIPELINES_JSON="$REPO_ROOT/.claude/skills/work-journal/pipelines.json"
HOOK="$REPO_ROOT/.claude/hooks/journal-flush.sh"
STATE_DIR="$REPO_ROOT/.claude/state"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

command -v jq >/dev/null || fail "jq required for this test"
[[ -f "$PIPELINES_JSON" ]] || fail "pipelines.json missing at $PIPELINES_JSON"
[[ -x "$HOOK" ]] || fail "flush hook not executable: $HOOK"

# Assertion 1: personal is local_only=true
personal_local_only=$(jq -r '.pipelines.personal.local_only' "$PIPELINES_JSON")
[[ "$personal_local_only" == "true" ]] || fail "personal.local_only must be true, got: $personal_local_only"
pass "personal.local_only=true"

# Assertion 1b: personal has no doc_id
personal_doc=$(jq -r '.pipelines.personal.doc_id // "null"' "$PIPELINES_JSON")
[[ "$personal_doc" == "null" ]] || fail "personal.doc_id must be null, got: $personal_doc"
pass "personal.doc_id=null"

# Assertion 2: every work pipeline is local_only=false
for pipeline in applications paper6 swarm_ops content consulting; do
  flag=$(jq -r --arg p "$pipeline" '.pipelines[$p].local_only' "$PIPELINES_JSON")
  [[ "$flag" == "false" ]] || fail "$pipeline.local_only must be false, got: $flag"
  pass "$pipeline.local_only=false"
done

# Assertion 3: DRY_RUN flush for personal never emits a drive-sync action
mkdir -p "$STATE_DIR"
tmpdraft="$STATE_DIR/journal-draft-personal.md"
cleanup() { rm -f "$tmpdraft"; }
trap cleanup EXIT

cat > "$tmpdraft" <<'EOF'
## 2026-04-19 00:00 — privacy test entry

**Kind:** discovered
**Pipeline:** personal

This is test content that must never reach Google Drive.

---
EOF

# Seed a personal doc_id to prove local_only wins over doc_id presence
tmp_pipelines="$(mktemp)"
jq '.pipelines.personal.doc_id = "MUST_NEVER_BE_USED"' "$PIPELINES_JSON" > "$tmp_pipelines"
restore_pipelines() { mv "$tmp_pipelines" "$PIPELINES_JSON.bak.$$" 2>/dev/null || true; rm -f "$tmp_pipelines"; }
orig_pipelines="$(mktemp)"
cp "$PIPELINES_JSON" "$orig_pipelines"
cp "$tmp_pipelines" "$PIPELINES_JSON"
restore_orig() { cp "$orig_pipelines" "$PIPELINES_JSON"; rm -f "$orig_pipelines" "$tmp_pipelines"; }
trap 'cleanup; restore_orig' EXIT

output=$(DRY_RUN=1 bash "$HOOK" 2>&1 || true)

echo "--- hook output ---"
echo "$output"
echo "--- end hook output ---"

if echo "$output" | grep -q "pipeline=personal"; then
  if echo "$output" | grep -E "pipeline=personal.*drive-sync" >/dev/null; then
    fail "personal pipeline triggered a drive-sync action"
  fi
  if echo "$output" | grep -E "drive-sync marker for doc_id=MUST_NEVER_BE_USED" >/dev/null; then
    fail "personal pipeline would have emitted marker with poisoned doc_id"
  fi
  pass "personal DRY_RUN did not trigger drive-sync"
else
  fail "hook did not process the personal draft"
fi

# Draft must still exist (DRY_RUN doesn't delete)
[[ -f "$tmpdraft" ]] || fail "DRY_RUN should not delete the draft"
pass "DRY_RUN left draft intact"

echo
echo "ALL PRIVACY CHECKS PASSED"
