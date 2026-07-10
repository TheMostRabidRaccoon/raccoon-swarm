# The Autonomy Ladder — Autonomous Creation, Governed Integration

**Status:** DESIGN — proposed, not built. Conductor red-pen expected before any rung ships.
**Author:** drafted with Claude Code, 2026-07-07. Amended 2026-07-09: collaboration model
replaced with **Led Builds**; ladder revised (Rung -1 tool spine added, auto-merge removed
from v1); the five open questions resolved. For Conductor ratification.
**One line:** *The swarm may independently produce reviewable software artifacts. It may not
touch protected branches, secrets, deploys, or permissions without a human gate.*

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

**Known limit — documented now so it cannot be miscited later.** `authored_by` is
*submission* provenance: which API produced the diff, stamped by the runner. It is
**not** *idea* provenance — it does not record which seat conceived the work. In a
shared-context council a seat can ghost-write a diff another seat triggers. That is
fine for accountability; it is wrong as authorship-of-idea. Do not cite `authored_by`
as idea-provenance in Paper 2 or anywhere else.

---

## The ladder

Revised. The floor is unchanged; the collaboration rung is **Led Builds**, not solo
branches and not baton-passing; auto-merge is removed from v1.

```
Rung -1  Tool spine        MCP parity + evidence tools wired + stateful code_exec
Rung  0  Attribution floor runner-stamped receipts (build first, always)
Rung  1  Read              GitHub App / PAT, least privilege, SHA-cited claims
Rung  2  Led Builds        swarm-lab; one seat leads, others assist, leader owns
Rung  3  Draft PRs         council review → Conductor gate
   —     (former auto-merge rung: removed from v1 — see Decisions)
```

Above every rung, permanently: **the human integration gate.** Nothing merges into
anything that runs without Conductor approval. That gate is non-negotiable, and by
itself it protects the merge path most of this document's caution is spent guarding.

### Rung -1 — Tool spine (the substrate)

Before autonomous creation is worth turning on, the seats need something to build
*with* and receipts to build *on*. This is numbered below the floor because it is the
material the lab works in — but it proceeds *together with* Rung 0 at the start.

- **MCP parity.** Generate the external MCP surface from (or run a parity check
  against) `swarm_tools.py`, so a tool exists whether a seat is reached by native
  tool-use or by MCP. Today `swarm_tools.py` registers more tools
  (`web_verify`, `filestore_semantic_search`, `prosody_analyze`,
  `dispatch_queue_write`) than `raccoon_mcp_server.py` exposes. That gap is a
  Rung -1 bug, and closing it at the source kills the *class* of gap instead of
  patching today's instance.
- **Evidence tools wired.** `evidence_search / evidence_fetch /
  evidence_resolve_citation` over the existing `swarm_evidence.py` catalog — which is
  built (source IDs, content hashes, chunk indexes, dedup) but currently ships no
  model-facing tools.
- **Stateful `code_exec`.** Persistent sessions so a build can accrete across turns
  instead of dying at each sandbox boundary. Single-shot execution is fine for
  "compute this"; it cannot support "build this."

### Rung 0 — Attribution floor (build first, always)

Runner-stamped `authored_by / executed_by / tests_passed / base_sha`, seat-unforgeable
(full spec above). Nothing above this rung turns on until a seat *cannot* forge which
seat, which runner, which tests, which SHA.

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
- **Repo-state claims must cite the manifest SHA** — mandatory, not optional — so a
  claim that was true at mirror time cannot be silently re-quoted after the mirror
  has moved.

### Rung 2 — Led Builds (the collaboration model)

One seat leads. The others assist. The leader owns the artifact. This replaces both
the draft's per-seat solo structure (five soloists building in parallel) and the
baton-passing alternative raised in review (a polite, sequential relay race). Neither
is what this system was asked to demonstrate.

```yaml
led_build:
  leader: <seat>                    # council-assigned or rotating, per project
  branch: swarm/led/<seat>/<slug>   # lab repo only
  leader_may:
    - commit                        # sole commit authority on the branch
    - invoke_helper(seat, ask)      # a question or a bounded subtask
    - declare_done                  # opens the draft PR
  helper_may:
    - respond                       # that's it
  helper_may_not:
    - commit
    - invoke                        # no helper-calls-helper; depth caps at leader -> helper
  attribution:
    authored_by: leader             # every commit, no exceptions
    helper_contributions:           # logged, never authorship
      to: BUILD_LOG.md              # seat, ask, response ref, timestamp
  caps:
    invoke_depth: 2                 # leader -> helper, full stop
    helper_calls_per_build: 20      # config value, tune from lab data
    token_budget: per-build         # set at kickoff
  exit:
    draft PR -> council review -> Conductor gate
```

**Why this keeps Rung 0 intact.** The leader is `authored_by` on every commit the way
a tech lead owns a PR after consulting five colleagues. Helper invocations are
*inputs* — logged to `BUILD_LOG.md` (seat, ask, response ref, timestamp), auditable,
never authorship. The attribution floor does not bend; the collaboration was
restructured so it does not have to. The "authorship is mush" problem only existed
under *symmetric* peer invocation (any seat calls any seat, output comes back
interwoven), which this does not ship.

**Why live invocation is not a new capability grant.** Live multi-model exchange is
this swarm's incumbent operating mode — 140+ sessions of cross-synthesis, dual-grader
adjudication, deadlock resolution. The only delta in a Led Build is that the exchange
produces git artifacts instead of session transcripts. The floor was designed for
exactly that delta.

### Rung 3 — Draft PR (the sweet spot — free for every seat)

The leader's `declare_done` opens a **draft** PR. Council review, then the Conductor
gate. This is where creation lives: code, tests, argument, revision, all preserved as
reviewable artifacts. No reliability score gates creation — it is universal. The
Conductor wakes to branches and PRs, not vapor.

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
  changes there are top-rung, full stop.
- Private-repo work executes in **isolated runners** with scrubbed env, never
  with the swarm's live secrets in scope.

This is `swarm_deploy.py`'s fail-closed doctrine extended to the CI boundary.

---

## The playground — `swarm-lab` (build here FIRST)

Not a fun add-on — the **safest rung and the proving ground** for the whole
machinery. Build attribution, receipts, the Led Build protocol, and the promotion
vote in a repo where blast radius is zero; watch how they fail; *then* graduate the
proven mechanism to `raccoon-swarm`.

- A dedicated `swarm-lab` repo (see Decisions) for weird prototypes.
- Scheduled **Led Builds**: one seat leads, the others assist, per the Rung-2 protocol.
- Every build leaves a **receipt**: branch, `BUILD_LOG.md`, tests or screenshot, and a
  short "why this is interesting."
- The council **votes to promote** a build into a real PR.

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

Each seat gets a **daily draft-PR / compute allowance**, spendable without
the Conductor. Prevents a runaway seat from flooding the queue; makes "agency"
concrete and bounded.
- **2–3 draft PRs per seat per day.** Budget to the Conductor's *reading* speed —
  the review is the bottleneck, not the models' output speed.
- **Led Build caps** as specified in Rung 2: `invoke_depth: 2`,
  `helper_calls_per_build: ~20`, per-build token budget set at kickoff.
- Budgets refill daily; unused budget does not roll over (no hoarding-then-flooding).
- Orthogonal to reliability: budget caps *volume*, reliability caps *integration speed*.

---

## Reliability scores — deferred with the fast lane

Seat reliability (per-seat phantom rate, false-conviction rate, honest-verb
compliance, CI pass rate) was specified to gate the auto-merge fast lane. **With
auto-merge removed from v1, reliability scoring is deferred with it** — it re-enters
only when an auto-merge lane is proposed post-lab.

When it returns, the two hard rules stand:
1. **It never gates creation (Rungs 1–3).** If a low-reliability seat also gets fewer
   chances to build clean receipts, it death-spirals. Everyone always branches and
   opens drafts; only clean receipts earn auto-merge.
2. **It is recency-weighted.** A seat that just got a fix (e.g. Grok's reasoning bump,
   PR #89) must be able to climb back fast. A stale lifetime average punishes a fixed
   model for old failures and disincentivizes the exact repairs we want.

---

## Build order

Built one piece at a time; each earns the next. **Do not turn on multiple rungs at
once.**

0. **Attribution floor (Rung 0)** — runner-stamped
   `authored_by/executed_by/tests_passed/base_sha` + signed bot commits. Smallest
   piece; everything rests on it.
1. **Tool spine (Rung -1)** — MCP parity + evidence tools wired + stateful `code_exec`.
   Proceeds alongside the floor; it is the substrate the lab builds with.
2. **Read (Rung 1)** — GitHub App / PAT, mirror + manifest, SHA-cited claims —
   **on `swarm-lab` only.**
3. **Led Builds in the lab (Rung 2)** — leader/helper protocol + `BUILD_LOG.md`; prove
   creation + receipts where blast radius is zero.
4. **Draft PRs + council promotion in the lab (Rung 3)** — prove the promotion vote and
   the calibration-driven idea lifecycle where nothing production can break.
5. **Graduate to `raccoon-swarm`** with the danger-zone ruleset and CI hardening — only
   after the lab has shown the failure modes.

Auto-merge and symmetric peer invocation are **not** on this v1 order; each carries a
named earning-condition below.

---

## Decisions (the draft's five open questions, resolved)

1. **Lab repo vs. monorepo → separate repo.** A repo with no secrets solves the
   CI-secrets problem *structurally* instead of by discipline.
2. **App vs. PAT → PAT to prototype, App before anything graduates** to
   `raccoon-swarm`. Don't let App setup yak-shave block Rungs 0–2.
3. **Rung-4 thresholds → deferred.** Setting them before lab data exists violates this
   doc's own measure-first doctrine.
4. **Budgets → 2–3 draft PRs / seat / day; Led Build caps as specified.** Budget to
   Conductor reading speed.
5. **Auto-merge in v1 → no.** Q5 was never independent of Q3: thresholds that can't
   exist yet can't gate anything. The auto-merge rung is definitionally post-lab.

---

## Named deferrals (so they can't quietly become never)

- **Auto-merge (tiny low-risk lanes).** Unlocks for design once the lab has a full
  quarter of clean Led-Build receipts; thresholds are set from that data, not from
  vibes.
- **Symmetric peer invocation (any seat calls any seat).** Unlocks for lab evaluation
  when **≥3 Led Builds have been promoted through council review AND ≥1 `BUILD_LOG`
  shows a build where the leader-bottleneck demonstrably cost the artifact** (a helper
  had the decisive contribution but couldn't act on it). If the leader never
  bottlenecks, symmetric invoke was never needed. If it does, we'll hold the exact
  receipt that justifies engineering around the attribution floor carefully.

---

## Season One

Five Led Builds, each seat leads one, portfolio-grade targets pitched by the leader at
kickoff and ratified by the council. Candidate slate:

- `deck_draw` — server-side verifiable randomness; entropy the seats can't narrate.
- RRI site intake-triage agent with subagent delegation.
- Corpus query surface over the dissent-event data.
- Leader's choice ×2.

Per-build deliverable: working artifact + `BUILD_LOG.md` + draft PR. Aggregate
deliverable: five AI systems, each architected by a different frontier model directing
the other four — with full provenance receipts.

---

## What stays true throughout

- **Creation is free; integration is governed.** The gate is at merge, keyed to
  blast radius, never at the keyboard.
- **The council proposes; a single accountable agent (Claude Code) + a human
  still own the merge to `main`.** Direct council write-to-`main` is not on this
  ladder.
- **Every rung is measure-first.** Prove it in the lab, score it, then let the
  data — not vibes — earn the next rung.
