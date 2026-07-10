# Prompt 01 — Bootstrap portfolio strategy

Paste the Portfolio Factory Charter before this prompt.

---

## Job

Create the RRI portfolio strategy and build backlog. Do **not** attempt to build all demos in this session.

## Repositories

- `TheMostRabidRaccoon/raccoon-swarm` — builder swarm, tool registry, headless/daemon execution, memory, dispatch patterns.
- `TheMostRabidRaccoon/rri-website` — current marketing site and existing system demonstrations.
- Proposed: `TheMostRabidRaccoon/rri-workspace-lab` — reusable interactive demo shell.

## Required portfolio shape

Select exactly twelve primary portfolio entries:

- four truthful flagship systems from existing RRI work;
- eight small-business workspace sandboxes;
- move unfinished or weakly aligned projects to an R&D/Lab section rather than inflating their status.

Use the following candidate workspace set unless evidence supports a better substitution:

- Latch — lead intake and qualification
- Scope — discovery to proposal
- Front Desk — inbox, voicemail, and scheduling
- Fieldline — field-service dispatch
- Ledger — cash flow and collections
- Foundry — knowledge and SOP operations
- Signal — reviews and reputation
- Control Room — owner daily brief

## Evaluation rubric

Score every candidate from 1–5:

- buyer relevance — 25%
- proof of architectural depth — 20%
- visual/demo clarity — 15%
- interactivity — 15%
- reusable components — 10%
- implementation effort — 10% inverse
- public-demo safety — 5%

## Required artifacts

Write or update:

1. `portfolio-factory/charter.md`
2. `portfolio-factory/portfolio-map.json`
3. `portfolio-factory/positioning.md`
4. `portfolio-factory/architecture.md`
5. `portfolio-factory/backlog.json`
6. `portfolio-factory/tooling-gap.md`
7. `portfolio-factory/decisions/portfolio-v1.md`

## Architecture decisions to close

- Separate factory, runtime, and presentation planes.
- Decide whether the Workspace Lab is a new repo or a subdirectory.
- Define one reusable dashboard shell rather than twelve bespoke applications.
- Define replay, try, live, inspect, and reset modes.
- Define the common event schema.
- Define demo data policy and human gates.
- Define first three demos and why they lead.
- Identify which current tools are sufficient and which repository/preview/browser tools are missing.
- Produce an implementation backlog of bounded jobs with dependencies, model routes, path allowlists, budgets, and acceptance criteria.

## Non-goals

- No fake ROI.
- No redesign-by-committee of the entire brand.
- No live access to real Gmail, QuickBooks, calendars, CRMs, or client data.
- No code dumped into an untracked artifact without a path and next step.

End with `PORTFOLIO_JOB_RESULT`.
