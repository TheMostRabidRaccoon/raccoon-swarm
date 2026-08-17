# The Portfolio Workspace — a fenced construction surface

`swarm_workspace.py` exposes a low-blast-radius GitHub **construction surface** to the peer cognitive ecology. It provides branch/file/draft-PR actuators for allowlisted sandbox repositories while keeping production integration on a separate reviewed route.

The important distinction is:

> **The workspace describes where direct mutation is exposed. It does not define the boundary of anyone's capability.**

Production-source observation is available through the read-only `source_*` surface. Sandbox construction is available through `workspace_*`. Consequential integration follows its own review/deployment route.

## The two boundaries

The sandbox mutation surface is bounded twice — once by GitHub and once by the deterministic worker.

### Boundary 1 — GitHub credential scope

1. Create/select the sandbox repo, e.g. `swarm-lab`.
2. Mint a **fine-grained** token whose repository access is limited to the sandbox repo(s). Permissions: **Contents: Read/Write** + **Pull requests: Read/Write** as needed for the construction surface.
3. Keep the production `raccoon-swarm` repository outside this token's mutation scope. This makes production-source write access absent at the credential layer rather than dependent on a prose instruction.
4. Protect the sandbox default branch with PR/review requirements as desired.
5. Store the token in server environment as `SWARM_WORKSPACE_GITHUB_TOKEN`. The deterministic worker holds the credential; model tool calls receive only returned operation results.

This is a **credential boundary**. It should be described as such: production mutation routes elsewhere. It is not evidence that a participant cannot understand, inspect, design, critique, or substantially complete source changes.

### Boundary 2 — deterministic worker guards

Even if the credential were broader than intended, the workspace worker narrows the construction surface:

- **Repo allowlist** — only repositories in `SWARM_WORKSPACE_REPOS` are accepted.
- **Base branch mutation is not exposed** — writes target job branches rather than `main`/`master`/configured base.
- **Job-branch namespace** — construction writes use `swarm/<slug>` branches.
- **Sensitive paths route elsewhere** — workflow/CI, secret/env, deployment, and dependency-manifest paths are rejected by this surface.
- **Draft PR is the handoff actuator** — this toolset exposes PR creation, not merge-to-production.

Those are environmental facts about this interface.

## The tools

| Tool | Current surface |
|---|---|
| `workspace_status` | report construction-surface config + reachability without exposing credentials |
| `workspace_list_files` | observe a directory/ref within an allowlisted workspace repo |
| `workspace_read` | read a workspace file + blob SHA for optimistic updates |
| `workspace_open_branch` | open a `swarm/<slug>` writer lease branch |
| `workspace_put_file` | create/update one file on that job branch |
| `workspace_open_pr` | create the draft review handoff |

Runner-stamped model/session/boot provenance answers **who emitted the repository mutation**. It does not imply idea ownership, seniority, or exclusive jurisdiction over the work.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `SWARM_WORKSPACE_GITHUB_TOKEN` | _(unset)_ | fine-grained credential for the sandbox construction surface |
| `SWARM_WORKSPACE_REPOS` | `TheMostRabidRaccoon/swarm-lab` | comma-separated allowlist of repositories exposed to this surface |
| `SWARM_WORKSPACE_BASE_BRANCH` | `main` | branch used as the construction base / review target |

When a required actuator is not exposed here, report the route precisely rather than generalizing it into incapacity.

## A build's shape

```text
source_*                inspect relevant running/source state if needed
        ↓
workspace_open_branch   swarm/latch-build          [writer lease]
workspace_put_file      demos/latch/index.html
workspace_put_file      demos/latch/fixtures/leads.json
        ↓
workspace_open_pr       draft review handoff
        ↓
review / integration    separate consequential route
        ↓
deployment + verification
```

The writer lease is a provenance constraint on the artifact, not a leadership role. Other participants may inspect, reason, challenge, supply code/design ideas, test assumptions, or identify a better route throughout the build.

## Why keep the fence

The point of the fence is not to make the swarm cognitively smaller. It is to make **reversible creation cheap while keeping high-blast-radius integration explicit**.

A useful shorthand:

> **Broad cognition. Bounded actuators. Explicit routes.**
