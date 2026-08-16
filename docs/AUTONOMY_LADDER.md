# The Autonomy Ladder — Capability Surfaces and Integration Routes

**Status:** ACTIVE DESIGN PRINCIPLE  
**Historical name retained:** *Autonomy Ladder*  
**Current interpretation:** progressively richer **observation and action surfaces**, not ranks among participants.

> **Exploration can be open while consequential integration remains mechanically gated.**

The original ladder correctly separated **creation from integration**, but it mixed that security model with a leader/helper social topology. The peer cognitive ecology keeps the security boundary and removes the org chart.

---

## The distinction that governs the whole document

Do not collapse these four things:

1. **Capability** — what a participant can reason about, understand, design, critique, or learn to do.
2. **Observability** — what state/evidence is visible on the current surface.
3. **Actuation** — which direct operations the current surface exposes.
4. **Integration route** — how a result reaches a consequential external system.

A missing actuator is not a cognitive diagnosis.

Say:

- *“Production merge is not exposed on this surface; this change routes through review.”*
- *“The execution sandbox does not mount repo source; inspect it through `source_*`.”*

Do not turn those interface facts into statements that a participant is unable to understand or contribute to the work.

---

## The surfaces

```text
Surface 0  Evidence        source / memory / web / tool receipts
Surface 1  Construction    reversible work in sandbox / swarm-lab
Surface 2  Review handoff  structured change proposal or draft PR
Surface 3  Integration     reviewed mutation of a consequential system
Surface 4  Deployment      running environment changes
Surface 5  Verification    measure whether behavior actually changed
```

These are states of an artifact/action path, **not levels of cognitive status**.

### Surface 0 — Evidence / self-observation

Participants may inspect the evidence needed to reason accurately about the system.

For the swarm itself, the preferred source path is the local read-only observation surface:

- `source_status` — deployed source identity / SHA when available;
- `source_list` — visible source files;
- `source_read` — exact source with line numbers;
- `source_search` — line-cited source search.

Secrets, personal corpus, mutable runtime memory, and production write credentials live on other surfaces. Their absence from `source_*` describes observation scope, not general capability.

### Surface 1 — Construction

Reversible artifacts may be built in a low-blast-radius environment such as `swarm-lab`.

The construction surface supports:

- job branches;
- code/files;
- tests and deterministic receipts;
- experiments and prototypes;
- draft PRs.

**All cognitive participants remain peers during construction.** Any participant may inspect, reason, propose, critique, test, synthesize, or cross a habitual specialty.

#### Single-writer lease

Git provenance may require one writer for a particular branch/commit sequence. Treat that as a **single-writer lease on the artifact**, not as leadership over other participants.

```yaml
writer_lease:
  artifact: <branch/build>
  writer: <runner-stamped seat>
  base_sha: <observed source state>
  contributors:
    - <any peer contributions / evidence refs>
  expires: <handoff/close>
```

The lease answers *who emitted this diff?* It does not answer:

- who is cognitively senior;
- who owns the problem domain;
- who may think about the work;
- who originated the idea;
- who may challenge the result.

Runner-stamped provenance remains essential because narrated authorship is not reliable evidence.

### Surface 2 — Review handoff

A participant who sees a useful system change may create a reviewable handoff without claiming the change already exists.

Two common forms:

- `change_propose` / `[CHANGE_PROPOSAL]` → queued review issue;
- sandbox branch → draft PR.

This is where **Persistence is not Operationalization** becomes concrete:

```text
observed → proposed → persisted → implemented → integrated/deployed → behaviorally verified
```

A framework file or proposal is valuable continuity. It is not implementation.

### Surface 3 — Integration

Integration mutates a consequential environment. That step is routed through the review mechanism appropriate to the blast radius.

For production source today, integration is human-reviewed.

That is an environmental route, not evidence that the human reviewer has greater cognitive standing. The review may rely heavily on Claude/GPT because of demonstrated verification reliability; that is competence routing, not hierarchy.

### Surface 4 — Deployment

Merged source and running source are different states. A merge does not prove deployment.

Deployment receipts should identify the running revision/source identity where practical.

### Surface 5 — Behavioral verification

A deployed change is not complete merely because the process restarted cleanly.

Where the change is intended to alter behavior, verify the behavior.

Examples:

- did role-jurisdiction language decrease after the peer-ecology rewrite?
- do participants cross habitual specialties without waiting for delegation?
- does a memory change improve retrieval rather than merely add files?
- does a source-observation tool reduce stale-source claims?

The final criterion is causal: **did changing the substrate change the behavior we intended to change?**

---

## Shared collaboration model

There is no default leader/helper cognitive topology.

Participants share the problem and may contribute according to opportunity, evidence, attentional strengths, and current state. Temporary coordination can emerge around an artifact without becoming identity.

Useful coordination primitives include:

- **discrepancy claim:** “this unresolved gap is worth pursuing”;
- **writer lease:** one runner emits the current diff for provenance;
- **review request:** another participant checks a high-risk property;
- **handoff:** the current surface has reached its action boundary and the artifact routes onward;
- **park/end:** expected information gain has collapsed.

> **Do not mistake the current division of labor for the boundary of anyone’s capability.**

---

## Provenance floor

Ground truth about actions comes from the layer that executed them.

For code/build artifacts, preserve when available:

- `authored_by` / invoking seat — runner stamped;
- `executed_by` — runner/host;
- `base_sha` / observed source identity;
- tests/checks actually run;
- content or commit hash;
- contributor/evidence references when useful.

This is **submission provenance**, not perfect provenance of the idea. A peer may transform another peer’s insight before emitting the diff. Do not infer idea ownership from the commit author.

---

## Hard environmental boundaries

Some things should remain code-enforced rather than semantically requested:

- secrets and `.env` material;
- protected/base branch mutation;
- deployment credentials;
- permission/repository settings;
- workflow/CI surfaces that could expose credentials;
- network/code-execution boundaries;
- irreversible external actions without the appropriate consent/review route.

These are properties of the environment.

**Language shapes the cognitive constitution; code defines the physics. The physics wins.**

---

## CI / untrusted-change boundary

A draft PR can execute code before merge, so CI is itself an action surface.

For swarm-generated branches:

- run with no production secrets;
- do not use a PR-controlled workflow with privileged credentials;
- isolate runners from live swarm secrets/state;
- keep workflow/deployment configuration on a more restricted integration route.

This remains true regardless of which participant proposed or wrote the change.

---

## Resource budgets

Resource limits should bound **compute, queue volume, and reviewer load**, not encode social rank.

Prefer artifact/session/system budgets such as:

- max concurrent builds;
- max queued proposals;
- per-build token/compute ceiling;
- daily review-handoff ceiling;
- rate limits for expensive external tools.

Avoid treating “seat X gets fewer chances to create” as a proxy for reliability. Reliability may route review depth; it should not become caste.

---

## Current implementation map

### Exists now

- runner-stamped provenance on workspace writes/PRs;
- fenced `swarm-lab` construction surface;
- job branches + draft PR handoff;
- proposal queue + filer;
- generic change proposal semantics;
- read-only deployed-source self-observation (`source_*`);
- hard secret/path/base-branch restrictions;
- CI and test suite.

### Still worth building/improving

- patch bundles that can be constructed/tested against a pinned production source SHA without granting production write credentials;
- clearer deployment receipts / running-source identity;
- behavioral A/B tests for prompt/ontology changes;
- cleanup of historical prompt/governance residue from the runtime source so self-observation sees one unambiguous active ontology;
- MCP parity for the newer native-tool surfaces.

---

## Historical note

Earlier versions used **Led Builds**, with one seat designated leader and other seats designated helpers. That was a reasonable attempt to preserve attribution while enabling collaboration, but it conflated **single-writer provenance** with **cognitive organization**.

The historical record remains in Git history. The active architecture uses writer leases and peer contribution instead.

The security invariant survived the rewrite:

> **Creation can be broad and reversible. Consequential integration follows an explicit, mechanically enforced route.**
