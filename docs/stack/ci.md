# CI

GitHub Actions workflows.

## Source of truth

- `.github/workflows/*.yml`

## Workflows

### `work-journal-privacy.yml`

Blocking privacy test for the work-journal skill.

- **Triggers**
  - `pull_request` touching `.claude/skills/work-journal/**`,
    `.claude/hooks/journal-flush.sh`,
    `.claude/hooks/journal-sync-startup.sh`, or the workflow itself.
  - `push` to `main` with the same path filters.
- **Job**: `privacy-check` on `ubuntu-latest`.
- **Steps**
  1. `actions/checkout@v4`
  2. Install `jq`
  3. Run `.claude/skills/work-journal/tests/privacy-check.sh`
- **Invariant enforced**: the `personal` pipeline is local-only and can
  never produce a drive-sync marker. Test fails closed on misconfig
  (missing `local_only`, `personal.doc_id` set, any `local_only` pipeline
  emitting a marker).

## Conventions

- One workflow per invariant. Don't pile unrelated checks into one file.
- Fail closed. If a test can't determine safety, it fails.
- Keep steps thin — the logic lives in `.sh` scripts inside the repo so they
  can be run locally too.
