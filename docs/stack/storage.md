# Storage

Where state lives across restarts. Split between repo-tracked seeds,
runtime JSON files, and a Railway-attached volume.

## Source of truth

- `raccoon_swarm_server.py` (`STORAGE_DIR`, `MEMORY_FILE`, `IDEAS_FILE`, loaders)
- `swarm_memory_seed.json`
- `.gitignore` (what must never be committed)
- `journals/` (work-journal outputs)

## Storage roots

Two modes, selected by env:

| Mode     | Trigger                                             | `STORAGE_DIR` | `MEMORY_FILE`        |
|----------|-----------------------------------------------------|---------------|----------------------|
| Local    | No `RAILWAY_ENVIRONMENT` and no `RRI_STORAGE_DIR`   | `.` (repo)    | `./swarm_memory.json`|
| Hosted   | `RAILWAY_ENVIRONMENT` set OR `RRI_STORAGE_DIR` set  | `$RRI_STORAGE_DIR` (default `/data`) | `$STORAGE_DIR/swarm_memory.json` |

Initialisation: `raccoon_swarm_server.py:194-223`.

Subdirectories created under `STORAGE_DIR` in hosted mode:

- `logs/` — per-session JSON logs
- `outputs/` — generated DOCX transcripts
- `vault/` — `_vault_dir` (`:178`)
- `boot_context.md` — boot-time context file

## Swarm memory

- Runtime file: `swarm_memory.json` (gitignored)
- Seed file: `swarm_memory_seed.json` (committed)
- Backup: `swarm_memory.backup.json` (gitignored)
- Bootstrap order (`load_swarm_memory`, `:242`):
  1. `swarm_memory.json` if present
  2. else `swarm_memory_seed.json`
  3. else empty `_EMPTY_MEMORY`
- Write path: `save_swarm_memory` (`:269`); mutation: `update_swarm_memory` (`:369`).

## Ideas capture

- File: `ideas.json` under `STORAGE_DIR` (`:1092`). Gitignored.
- Routes: `POST /idea` (`:2098`), `GET /ideas` (`:2112`).

## Journals (work-journal skill)

- Directory: `journals/` — only `.gitkeep` committed; contents gitignored.
- Per-pipeline files: `journals/<pipeline>.md`.
- The `personal` pipeline is **local-only** — `personal.md` must never be
  committed and its drive-sync marker must never exist. Enforced by
  `.claude/hooks/journal-sync-startup.sh` and the CI privacy check.
- Drafts and drive-sync markers: `.claude/state/journal-draft-<pipeline>.md`
  and `.claude/state/pending-drive-sync-<pipeline>.md`. Both gitignored.

## Context / memory routes

| Route                 | Method   | Purpose                          |
|-----------------------|----------|----------------------------------|
| `/context`            | GET/POST | Read/write boot context          |
| `/memory`             | GET      | Dump swarm memory                |
| `/memory/clear`       | POST     | Reset to `_EMPTY_MEMORY`         |
| `/memory/pursuits`    | GET      | Current open pursuits            |

## What must never be committed

From `.gitignore`:

- `.env`, `.env.local`
- `ideas.json`, `swarm_memory.json`, `swarm_memory.backup.json`
- `vault/`, `raccoon_memory/`
- `journals/*` (except `.gitkeep`)
- `.claude/state/*` (except `.gitkeep`)
- `*.log`, `*.mp3`, `/tmp/`, `*.docx`
