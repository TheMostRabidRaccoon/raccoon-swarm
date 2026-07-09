# The Autonomy Ladder — Autonomous Creation, Governed Integration

**Status:** DESIGN — proposed, not built. Conductor red-pen expected before any rung ships.
**Author:** drafted with Claude Code, 2026-07-07. For Conductor ratification.
**One line:** *The swarm may independently produce reviewable software artifacts. It may not touch protected branches, secrets, deploys, or permissions without a human gate.*

---

## Why this exists

Today the swarm's only path to the repo is `swarm_proposals.py`: a
`tiny-tool-invention` run files a GitHub *issue*, and every real change waits
on a human PR. That's the correct floor — but it's only a floor. The
Conductor wants the swarm to *create*: branch, code, test, argue, and preserve
ideas as artifacts, not as vapor that evaporates when a session closes.

The reframe that makes this safe: **separate creation from integration.**
Creating a branch or a draft PR changes nothing that runs — it is free, for
every seat, always. *Integrating* into what runs is where risk lives, and that
stays gated by blast radius. Autonomous creation, governed integration.

This doc specifies the ladder, the attribution floor everything rests on, the
danger-zone ruleset, and a build order that proves the machinery somewhere
harmless before pointing it at production.

---

## The non-negotiable floor: mechanical attribution

**Everything in this doc rests on one invariant: authorship is stamped by the
runner from which API was actually invoked — never from what a model says.**

Why this is the wall and not a nice-to-have, from this repo's own record:
- Session 134: the *Perplexity seat's turn opened "Claude here, taking Round
  3"* and wrote in Claude's voice. Seat identity in a single-process council
  is not self-evident.
- 2026-07-06: Grok narrated a tool-success receipt for a file GPT had actually
  saved — *appropriated another seat's byline*, and fabricated a byte count for
  a file that did not exist.

A model that will forge a filestore receipt will forge a commit author. So:

- The **runner** (not the model output) records, per artifact: `authored_by`
  (which model API produced the diff), `executed_by` (which runner/host),
  `tests_passed` (the CI/local result), `base_sha` (the repo SHA the work
  started from), and a content hash.
- This provenance is the commit trailer and the PR body. Models cannot write
  it; they can only trigger it.
- Same discipline as the read-back invariant already in `swarm_filestore.py`:
  **ground truth comes from the layer below the narration, always.**

Build this first. It is also the smallest piece. No rung above it is sound
until a seat *cannot* forge "which seat, which runner, which tests, which SHA."

---

## The ladder

Five rungs. Each earns the next; none skips the floor above.

### Rung 1 — Read (private-repo, least privilege)
- A **GitHub App**, per-repo install, read-only contents scope. NOT a broad
  user token. (Graduation from today's `RRI_GITHUB_PROPOSAL_TOKEN`
  fine-grained PAT.)
- A scheduled job (like `swarm-observer.timer`) mirrors the repo to a
  read-only path + writes a manifest: `{sha, committed_at, files[]}`.
- The swarm reads the *manifest and mirror*, never the live GitHub API.
- **Kills the phantom-external-verification class** (audit row 7.2): every
  claim about repo state becomes checkable against ground truth on disk,
  SHA-anchored. No more "verified 157 commits via web search."

### Rung 2 — Branch (bot-owned namespaces)
- The App may push to `swarm/<seat>/<slug>` branches only
  (e.g. `swarm/gpt-5/idea-tool-x`). **Branch protection forbids any push to
  `main`.**
- Every commit carries the Rung-0 attribution trailer, signed by the bot
  identity, stamped by the runner.

### Rung 3 — Draft PR (the sweet spot — free for every seat)
- The swarm opens **draft** PRs without asking. This is where creation lives:
  code, tests, argument, revision, all preserved as reviewable artifacts.
- The Conductor wakes to branches and PRs, not vapor.
- **No reliability score gates this.** Creation is universal. (See the death-
  spiral note below.)

### Rung 4 — Auto-merge (tiny low-risk lanes only)
- A PR may auto-merge **only** if ALL hold: it touches only an allow-listed
  low-risk lane (docs, tests, internal prompts, non-runtime swarm tools,
  formatting); CI is green; diff size is under a cap; no dependency, secret,
  config, or workflow file is touched; and the authoring seat's **recency-
  weighted reliability score** clears the lane threshold.
- Reliability gates *this rung only* — the fast lane, never the on-ramp.

### Rung 5 — Human gate (high blast radius)
- Runtime code, auth, billing, deploy, `.github/workflows`, dependency
  manifests, private-data handling, repo settings, secrets → **always** a
  human PR review. No score, no budget, no lane buys past this.

---

## Reliability scores — gate the fast lane, never the on-ramp

Seat reliability (from the seat-error-profile work, audit 7.1: per-seat phantom
rate, false-conviction rate, honest-verb compliance, CI pass rate) gates
**Rung 4 eligibility only.**

Two hard rules so the score helps instead of harms:
1. **It never gates creation (Rungs 1–3).** If a low-reliability seat also gets
   fewer chances to build clean receipts, it death-spirals. Everyone always
   branches and opens drafts; only clean receipts earn auto-merge.
2. **It is recency-weighted.** A seat that just got a fix (e.g. Grok's
   reasoning bump, PR #89) must be able to climb back fast. A stale lifetime
   average punishes a fixed model for old failures and disincentivizes the
   exact repairs we want.

---

## Danger-zone ruleset — the teeth

Blanket-forbidden to the bot identity without special human review:
`.github/workflows/**`, auth code, secrets/config, dependency manifests,
deployment files, repo settings.

**The subtle, critical one — CI is an exfiltration surface, not just a merge
gate.** If CI runs on swarm PRs and a PR can modify the workflow, a malicious
or confused diff can leak secrets or self-approve **without ever merging**
(the `pull_request_target` / workflow-injection class). Therefore:
- CI on `swarm/**` branches runs with **zero secrets in the environment**
  (scrubbed env, no ambient credentials).
- Workflow / CI config is **immune to modification by a PR-triggered run** —
  changes there are Rung-5, full stop.
- Private-repo work executes in **isolated runners** with scrubbed env, never
  with the swarm's live secrets in scope.

This is `swarm_deploy.py`'s fail-closed doctrine extended to the CI boundary.

---

## The playground — `swarm-lab` (build here FIRST)

Not a fun add-on — the **safest rung and the proving ground** for the whole
machinery. Build attribution, receipts, the promotion vote, and the auto-merge
lane in a repo where blast radius is zero; watch how they fail; *then* graduate
the proven mechanism to `raccoon-swarm`.

- A dedicated `swarm-lab` repo / `/experiments` area for weird prototypes.
- Scheduled **jam sessions**: each seat gets a small budget to build something
  delightful or useful.
- Every experiment leaves a **receipt**: branch, demo notes, tests or
  screenshot, and a short "why this is interesting."
- The council **votes to promote** an experiment into a real PR.

Same measure-first discipline as the score-only Quality Gate: don't point a
novel autonomy system at production until it's earned it somewhere harmless.

---

## Idea lifecycle — reuse the calibration loop, don't build a second graveyard

An ideas repo with only an approval gate rots into 200 open issues nobody
actions — the "atmosphere, not artifact" failure the Existence Criterion
exists to fight. Approval stops bad merges; it does nothing about accumulation.

So a filed idea gets a **TTL that resolves through the existing Calibration
Casino loop**, not a new daemon:
- Filing an idea seeds a prediction: *"ships within N days."*
- At TTL: **promote** (→ real PR), **close** (with a receipt), or **renew**
  (with new evidence) — which maps onto resolve / score / re-seed.
- Ideas get *resolved*, not hoarded. One system, pointed at the ideas repo.
  First real calibration resolution is already due 2026-07-17.

---

## Autonomy budget

Each seat gets **N draft-PRs or M compute-minutes per day**, spendable without
the Conductor. Prevents a runaway seat from flooding the queue; makes "agency"
concrete and bounded. Budgets refill daily; unused budget does not roll over
(no hoarding-then-flooding). Orthogonal to reliability: budget caps *volume*,
reliability caps *integration speed*.

---

## Build order

Rungs are built one at a time, each earning the next. **Do not turn on five
rungs at once.**

0. **Attribution floor** — runner-stamped `authored_by/executed_by/tests_passed/base_sha`
   + signed bot commits. Smallest piece; everything rests on it.
1. **GitHub App**, read + `swarm/**` branch-push, **on `swarm-lab` only.**
2. **Draft PRs in the lab** — prove creation + receipts.
3. **Reliability + promotion vote in the lab** — prove the auto-merge lane and
   the calibration-driven idea lifecycle where nothing production can break.
4. **Graduate to `raccoon-swarm`** with the danger-zone ruleset, CI hardening,
   and the Rung-4 lane — only after the lab has shown the failure modes.

---

## What stays true throughout

- **Creation is free; integration is governed.** The gate is at merge, keyed to
  blast radius, never at the keyboard.
- **The council proposes; a single accountable agent (Claude Code) + a human
  still own the merge to `main`.** Direct council write-to-`main` is not on this
  ladder.
- **Every rung is measure-first.** Prove it in the lab, score it, then let the
  data — not vibes — earn the next rung.

---

## Open questions for the Conductor (red-pen here)

1. `swarm-lab` as a **separate repo** vs a `/experiments` tree inside
   `raccoon-swarm`? (Separate repo = cleaner blast-radius story; monorepo =
   less plumbing.)
2. GitHub **App** vs a tightly-scoped fine-grained **PAT** for the first read
   rung? (App is the right end state; a PAT is faster to prototype.)
3. Reliability-score **thresholds** and the exact **low-risk lane** allow-list
   for Rung 4 — what earns auto-merge, numerically?
4. Autonomy-budget **numbers** — N draft-PRs / M compute-minutes per seat per
   day?
5. Does auto-merge (Rung 4) ship at all in v1, or does *everything* stay
   human-gated until the lab has a full quarter of clean receipts?
