# The Portfolio Workspace — the swarm's fenced repo yard

The swarm has memory, code execution, and web tools — but historically no way to
touch a repository. This module (`swarm_workspace.py`, exposed as the
`workspace_*` tools) gives it a **fenced yard**: it can open branches and draft
pull requests in a *sandbox* repo, and it can never touch its own source, push to
`main`, or merge.

This is Rung 2 → Rung 3 of the Autonomy Ladder made real: *creation is free,
integration is governed.*

## The two boundaries

**"The swarm can't change its own code" is enforced twice — once by GitHub, once
by this module.**

### Boundary 1 — GitHub (the real one; you set this up once)

1. **Create the sandbox repo** — a private repo, e.g. `swarm-lab`.
2. **Mint a _fine-grained_ Personal Access Token** (Settings → Developer settings
   → Fine-grained tokens). Under **Repository access → Only select repositories**,
   pick **only `swarm-lab`**. Permissions: **Contents: Read/Write** +
   **Pull requests: Read/Write**. Nothing else.
   - 🔑 **Do not include `raccoon-swarm` in the token's repo list.** That single
     choice is what makes "the swarm can't touch its own source" true at the API
     layer — the token literally cannot see raccoon-swarm. A *classic* PAT is
     account-wide and would defeat this; use a fine-grained, single-repo token.
3. **Turn on branch protection** for the sandbox repo's default branch: require a
   pull request + at least one approving review, and block direct pushes. Now
   even the token can't self-merge — every build lands as a draft PR the
   Conductor approves.
4. Put the token in the server env as `SWARM_WORKSPACE_GITHUB_TOKEN`. The worker
   holds it; **it is never exposed to a model.**

### Boundary 2 — this module (defense in depth)

Even with a broader token, every op refuses to step outside the yard:

- **Repo allowlist** — refuses any repo not in `SWARM_WORKSPACE_REPOS`
  (default `TheMostRabidRaccoon/swarm-lab`). raccoon-swarm is not on it.
- **Base branch is unwritable** — `main`/`master`/`SWARM_WORKSPACE_BASE_BRANCH`
  can never be created or committed to.
- **Job branches only** — writes must target a `swarm/<slug>` lease branch.
- **Forbidden paths** — workflow/CI files, secrets/`.env`, deploy files
  (Procfile, netlify.toml, Dockerfile, …), and dependency manifests/lockfiles
  are rejected — those are Conductor-only.
- **No merge op exists.** PRs are always opened as **draft**. There is no
  push-to-main and no merge in this toolset, by construction.

## The tools

| Tool | What it does |
|---|---|
| `workspace_status` | Config + reachability (never reveals the token) |
| `workspace_list_files` | List a directory at a ref |
| `workspace_read` | Read a file; returns content + blob sha (for optimistic updates) |
| `workspace_open_branch` | Create a `swarm/<slug>` job branch off the base |
| `workspace_put_file` | Create/update one file on a job branch (commits it) |
| `workspace_open_pr` | Open a **draft** PR into the base branch |

Every commit and PR is stamped with `model` + `session` + boot SHA provenance
(the Ladder's Rung-0 attribution floor).

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `SWARM_WORKSPACE_GITHUB_TOKEN` | _(unset)_ | Fine-grained token, sandbox repo only. Unset ⇒ ops fail closed. |
| `SWARM_WORKSPACE_REPOS` | `TheMostRabidRaccoon/swarm-lab` | Comma-separated `owner/repo` allowlist |
| `SWARM_WORKSPACE_BASE_BRANCH` | `main` | Base branch to fork from and protect |

## A build's shape

```
workspace_open_branch  swarm/latch-build
workspace_put_file     demos/latch/index.html   (repeat per file)
workspace_put_file     demos/latch/fixtures/leads.json
workspace_open_pr      head=swarm/latch-build  (draft)  →  EMAIL_CONDUCTOR [REVIEW]
```

The Conductor reviews the draft PR and merges. The swarm never does.
