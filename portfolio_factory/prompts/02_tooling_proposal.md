# Prompt 02 — Propose the Portfolio Workspace MCP

Paste the Portfolio Factory Charter before this prompt.

---

## Job

Design and file the narrow repository/preview/browser toolset needed for the Portfolio Factory to build code safely.

The current code-execution sandbox is not a repository workspace. Do not solve this by granting the swarm an unrestricted shell or a broad GitHub token.

## Required design

Propose a **Portfolio Workspace MCP** backed by a deterministic worker. It must expose narrow operations:

1. `workspace_open`
   - repo allowlist
   - base ref
   - generated branch under `swarm/`
   - allowed path globs
   - lease/job id

2. `workspace_list`
   - directory listing inside allowed paths

3. `workspace_read`
   - exact path
   - content hash returned for optimistic concurrency

4. `workspace_apply_patch`
   - unified diff only
   - requires expected content hashes
   - rejects paths outside allowlist
   - file-size and binary restrictions

5. `workspace_run_checks`
   - command allowlist defined by repository
   - no arbitrary shell
   - timeout, memory, network, output caps

6. `workspace_diff`
   - structured changed-file list and patch summary

7. `workspace_commit`
   - commit to job branch only
   - deterministic author identity
   - message includes job id

8. `workspace_preview`
   - request a Netlify/preview build through a worker-held credential
   - return preview URL and build manifest

9. `browser_check`
   - Playwright navigation, assertions, accessibility smoke test, console errors
   - screenshot artifacts

10. `workspace_open_pr`
    - create a pull request only
    - never merge
    - attach job result and acceptance matrix

## Security constraints

- Credentials remain in the worker, never in model context.
- Repositories are allowlisted.
- `main` and protected branches are never writable.
- Every write is path-scoped.
- Commands are repository-defined and allowlisted.
- Network is off during checks except explicit preview/browser actions.
- One active lease per branch.
- All operations are auditable.
- Public demo runtime cannot access these tools.
- Human review is required before registry promotion and merge.

## Existing autonomy handoff

Use the swarm's structured tool-proposal mechanism. Emit one or more parseable blocks in this exact envelope:

```text
[TOOL_PROPOSAL]
name: ...
description: ...
schema:
```json
{ ...valid JSON schema... }
```
risks:
...
test:
```python
# focused unit-test stub
```
[/TOOL_PROPOSAL]
```

Prefer one coherent service proposal plus operation schemas rather than ten vague issues.

## Required artifacts

1. `portfolio-factory/tooling/portfolio-workspace-mcp.md`
2. `portfolio-factory/tooling/threat-model.md`
3. `portfolio-factory/tooling/tool-schemas.json`
4. `portfolio-factory/tooling/test-plan.md`
5. One or more `[TOOL_PROPOSAL]` blocks for the existing proposal queue.

End with `PORTFOLIO_JOB_RESULT`.
