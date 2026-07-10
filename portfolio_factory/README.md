# RRI Portfolio Factory

A bounded, auditable swarm workflow for designing, building, testing, and publishing a portfolio of working AI workspaces.

## North star

The portfolio should prove one claim:

> Kyra Dawson designs governed, tool-using AI workspaces that turn scattered small-business operations into a coherent operating environment.

The proof is not twelve chat windows. Each project is a working sandbox with:

- a business scenario and synthetic tenant data;
- specialized agents with explicit responsibilities;
- MCP tools with least-privilege access;
- visible tool calls, decisions, artifacts, and human approval gates;
- a sleek operational dashboard;
- a replay mode that always works and a rate-limited live mode where useful;
- a case study explaining the architecture and tradeoffs.

## Three planes

### 1. Factory plane

Raccoon Swarm performs strategy, architecture, specification, review, red-teaming, and release decisions.

A deterministic Portfolio Worker owns repository checkout, branch creation, command execution, tests, screenshots, preview deployment, commits, and pull requests. Models do not receive an unrestricted shell or a token that can write to `main`.

### 2. Runtime plane

A constrained public demo gateway runs each workspace against synthetic data. Every demo receives only the MCP tools named in its allowlist. Public demos do not expose the swarm administration server, repository tools, code execution, secrets, or real client data.

### 3. Presentation plane

`rri-website` presents the profile, portfolio grid, case studies, and links to the interactive RRI Workspace Lab. The Lab is one reusable dashboard shell driven by project configuration, fixtures, and a common event stream.

## Recommended repository topology

```text
TheMostRabidRaccoon/raccoon-swarm
  portfolio_factory/
    queue/
    runner/
    prompts/
    schemas/
    portfolio_demo_server.py
    portfolio_tools.py

TheMostRabidRaccoon/rri-website
  work/
  case-studies/
  data/portfolio.json
  assets/

TheMostRabidRaccoon/rri-workspace-lab    # recommended new repo
  src/shell/
  src/widgets/
  src/demos/
  fixtures/
  schemas/
```

The main site remains stable and elegant. The Lab can use Vite + React + TypeScript without forcing a full migration of the existing marketing site.

## Execution model

Do not use one enormous prompt. Use a charter plus bounded jobs:

```text
portfolio map
  -> tooling gap
  -> factory foundation
  -> one demo spec
  -> one demo build
  -> visual review
  -> red team
  -> site integration
  -> release gate
  -> next demo
```

Each job has a budget, allowed paths, acceptance criteria, model route, retry ceiling, and human gates.

## Model routing

| Phase | Seats | Ownership |
|---|---|---|
| Strategy | GPT, Claude, Gemini, Grok, Perplexity | Diverge, challenge, select |
| Architecture/spec | GPT + Claude | GPT authors system contract; Claude edits and closes gaps |
| UI/visual | Gemini + Claude | Gemini owns experience; Claude checks clarity/accessibility |
| Implementation | GPT only, using repository MCP | One writer prevents merge-by-raccoon |
| Red team | Grok + Claude | Grok attacks; Claude verifies remediation |
| Evidence/current claims | Perplexity | Sources and labels anything unverified |
| Release | Claude + GPT | Independent acceptance check; deterministic CI is final arbiter |

## Job-state model

Reuse the existing atomic filesystem-queue pattern:

```text
queued -> processing -> review -> done
                 \-> blocked
                 \-> failed
```

A job result manifest records files changed, test commands, exit codes, screenshots, preview URL, risks, retries, and the next proposed job. No artifact path means the work does not exist.

## Public demo contract

Every demo must support:

1. **Watch** — a 45–90 second replay using a recorded event trace.
2. **Try** — deterministic synthetic scenario controls.
3. **Live** — optional, rate-limited model reasoning with a strict tool allowlist.
4. **Inspect** — an architecture panel and tool ledger.
5. **Reset** — destroys session state and restores fixtures.

Common event types:

```text
run.started
agent.started
agent.completed
tool.called
tool.completed
artifact.created
approval.requested
approval.resolved
decision.recorded
run.completed
run.failed
```

## Build order

### Wave 0 — Bootstrap

1. Run `00_factory_charter.md` as persistent project context.
2. Run `01_bootstrap.md` with all five seats.
3. Run `02_tooling_proposal.md`; file the repository-tool proposal through the existing proposal queue.
4. Human-review and merge the narrow repository MCP.
5. Implement the Portfolio Worker and job queue.

### Wave 1 — Shared product

1. Build the Workspace Lab shell.
2. Build the synthetic MCP connector kit.
3. Build the trace/replay engine.
4. Build portfolio manifest rendering and case-study templates.

### Wave 2 — First three demos

1. Latch — Lead Intake & Qualification.
2. Front Desk — Inbox, Voicemail & Scheduling.
3. Control Room — Owner Daily Brief.

These communicate the offer fastest and reuse the broadest connector set.

### Wave 3 — Remaining demos

Scope, Ledger, Foundry, Fieldline, and Signal. Then integrate the four flagship systems.

## Safe autonomy defaults

```json
{
  "rounds_per_job": 3,
  "max_chain_depth": 1,
  "max_daily_jobs": 4,
  "max_retries": 2,
  "merge_requires_human": true,
  "external_writes_require_human": true,
  "public_enable_requires_human": true
}
```

The swarm may design, test, commit to a branch, publish a preview, and open a pull request. It may not merge, change credentials, enable a paid integration, or write to a real third-party business system without a human gate.

## Current-server invocation pattern

Use the existing headless endpoint for bounded planning/review jobs:

```json
POST /headless
{
  "override_query": "<contents of one prompt file>",
  "rounds": 3,
  "models": ["gpt", "claude", "gemini", "grok", "perplexity"]
}
```

For unattended production, use a Portfolio Worker that selects the next queue item and calls `/headless` with that exact job. Do not let the generic memory selector choose build work.

## Files in this pack

- `profile/profile-copy.md`
- `catalog/portfolio_catalog.json`
- `schemas/portfolio_job.schema.json`
- `schemas/demo_config.example.json`
- `prompts/00_factory_charter.md`
- `prompts/01_bootstrap.md`
- `prompts/02_tooling_proposal.md`
- `prompts/03_foundation.md`
- `prompts/04_demo_spec.md`
- `prompts/05_demo_build.md`
- `prompts/06_red_team.md`
- `prompts/07_site_integration.md`
- `prompts/08_release_gate.md`
- `prompts/09_daemon_controller.md`
- `automation/portfolio_worker.md`
