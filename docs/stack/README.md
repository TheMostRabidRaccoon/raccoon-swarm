# Tech Stack Docs — LLM Memory Layer

Persistent, terse docs so any LLM (swarm, Claude Code, daemon) can reconstruct
the stack without re-reading `raccoon_swarm_server.py`. Optimize for scan
speed, not prose.

## Files

| Slice        | Covers                                                      |
|--------------|-------------------------------------------------------------|
| `runtime.md` | Language, framework, server, Python deps                    |
| `models.md`  | AI provider SDKs, base URLs, model IDs, voice casting       |
| `storage.md` | Persistent volume, swarm memory, journals, ideas, outputs   |
| `deploy.md`  | Railway, Procfile, env vars, local-vs-hosted split          |
| `auth.md`    | Auth token, password hash, login flow                       |
| `hooks.md`   | `.claude/` hooks and skills                                 |
| `ci.md`      | GitHub Actions workflows                                    |
| `gazette.md` | Daily Burrow + Play Gazette emails (receipts-only digests)  |

## Conventions

- Bullets over prose. Tables where shapes repeat.
- Every claim points at a file path (and line number if stable).
- No marketing language. If the LLM can't act on it, delete it.
- Each file opens with a one-line "what this is" then a `## Source of truth`
  block listing the files it mirrors. When those files change, this doc
  must be refreshed.

## Update protocol

1. A `PostToolUse` hook (`.claude/hooks/stack-doc-nudge.sh`) watches every
   `git push`. After a push it diffs the pushed commits against the last
   push (`origin/<branch>@{1}..HEAD` or `main..HEAD` if no prior upstream),
   and prints a banner naming every `docs/stack/*.md` whose source-of-truth
   files were touched.
2. Claude sees the banner in the transcript and refreshes those docs in a
   follow-up commit. The hook itself does not call MCP tools or edit files —
   it only surfaces the work.
3. Pushes that don't touch any source-of-truth file print nothing.

Same shape as the work-journal flush/sync hooks: bash surfaces, Claude acts.

## Non-goals

- Not a user-facing README — `../../README.md` owns that.
- Not a deploy runbook — operational detail belongs in `deploy.md`, not here.
- Not a changelog — git history owns that.
