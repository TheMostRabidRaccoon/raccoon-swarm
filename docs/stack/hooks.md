# Claude Code Hooks & Skills

What lives under `.claude/` and when each piece fires.

## Source of truth

- `.claude/settings.json`
- `.claude/hooks/*.sh`
- `.claude/skills/*/`

## Hooks

Configured in `.claude/settings.json`. The harness runs these — Claude does
not. Hooks surface work to Claude via stdout banners; Claude is the only
piece that can call MCP tools or edit files.

| Event         | Matcher | Script                                    | Purpose                                                                     |
|---------------|---------|-------------------------------------------|-----------------------------------------------------------------------------|
| `SessionStart`| `*`     | `.claude/hooks/journal-sync-startup.sh`   | Surface pending drive-sync markers + degraded-env banners                   |
| `SessionEnd`  | `*`     | `.claude/hooks/journal-flush.sh`          | Flush per-pipeline journal drafts to `journals/<pipeline>.md`; emit drive-sync markers for non-local pipelines |
| `PostToolUse` | `Bash`  | `.claude/hooks/stack-doc-nudge.sh`        | After `git push`, name which `docs/stack/*.md` files need a refresh         |

### `journal-sync-startup.sh`

- Scans `.claude/state/pending-drive-sync-*.md`.
- Checks degraded env (missing `jq`, missing `pipelines.json`, stale drafts >24h).
- Defense-in-depth: exits **non-zero** if `pending-drive-sync-personal.md`
  exists — the `personal` pipeline is local-only and must never sync.

### `journal-flush.sh`

- Reads `.claude/state/journal-draft-<pipeline>.md`.
- Appends to `journals/<pipeline>.md`.
- Emits `.claude/state/pending-drive-sync-<pipeline>.md` only if
  `local_only=false` AND `doc_id` set.
- `DRY_RUN=1` prints actions without side effects (used by the privacy test).

### `stack-doc-nudge.sh`

- Filters `tool_input.command` for `git push`; exits silently otherwise.
- Diffs the just-pushed commits and maps changed files to
  `docs/stack/*.md` slices via an internal path→doc table.
- Prints a banner listing docs to refresh; does not edit files.

## Skills

Directory: `.claude/skills/<skill>/`.

### `work-journal`

- `SKILL.md` — entry-point instructions.
- `entry-template.md` — journal entry format.
- `pipelines.json` — per-pipeline metadata (`local_only`, `local_path`, `doc_id`).
- `tests/privacy-check.sh` — blocking CI check that the `personal` pipeline
  can never emit a drive-sync marker. Wired in `.github/workflows/work-journal-privacy.yml`.

## State directory

`.claude/state/` is the scratchpad the hooks use to hand work to Claude:

- `journal-draft-<pipeline>.md` — drafts awaiting flush.
- `pending-drive-sync-<pipeline>.md` — flushed entries awaiting MCP append.

Everything in `.claude/state/` is gitignored except `.gitkeep`.
