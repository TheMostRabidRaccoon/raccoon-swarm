# GrowBot Whole-Swarm Embodiment RFC

> **Status: Council-recommended implementation baseline; pending Kyra's operational
> decisions, Drive-intent reconciliation, implementation, integration, and
> behavioral verification.**

**Provenance.** Distilled from Raccoon Swarm session 144 (2026-08-25, 3 rounds:
Claude, GPT, Grok, Gemini, final synthesis), which deliberated Codex's
whole-swarm embodiment RFC prompt against the merged PR #100 code and upstream
GrowBot. The full deliberation record and the amended consolidated packet
(A1–A17) live in the swarm filestore
(`artifacts/2026-08-25_claude_growbot-consolidated-handoff.md` plus GPT and
Grok supporting analyses). **This file is the repo-canonical engineering
distillation** — the repository is the canonical technical record; Drive and
the filestore hold discussion material, not competing specifications. Changes
land here by amendment PRs, appended history in git, never silent rewrites.

---

## 0. Terms and authority boundaries

| Term | Meaning | Authority |
|---|---|---|
| **Creature** | The persistent raccoon: identity, shared history, soul file, `creature_id` | Owned by no seat |
| **Body** | Actuators, sensors, firmware, walk-policy version, calibration, `body_id` | Firmware + deterministic code |
| **Waking seat** | One model temporarily driving the body under a revocable, expiring **lease** | Proposes only; code disposes |
| **Dream tier** | The whole Council's slow consolidation process | Proposes memory/identity patches only; never actuates |
| **Kyra** | Human node | Physical authorization, environment, e-stop re-arm, `identity_core` amendments |
| **Deterministic code** | Validator, arbiter, lease manager, safety kernel | Final admission authority over every action and memory mutation |

No seat — including the currently waking one — owns the creature.

## 1. Topology (v1)

- **One persistent creature, one physical body, one revocable waking-seat lease
  at a time.** The waking seat rotates between Council members across sessions.
- `creature_id` and `body_id` are explicit in every schema from day one, so a
  multi-body fleet later is replication, not a rewrite.
- "One body per model" is a **destination, deliberately deferred** — not
  rejected. Multi-body semantics (one soul across vessels vs. one creature per
  body) are intentionally undesigned until one body is trustworthy.
- The body never waits on multi-model deliberation for real-time movement.
  The Council does not vote on servo angles.

**Evidential status (independence audit, 2026-08-25).** The session-144
convergence on this topology was a **daisy-chain, not independent replication**:
GPT proposed it in R1; Grok, Claude, and Gemini each read the prior seats before
agreeing, and "the codebase agrees" is non-independent (SWARM_BRAIN.md was
authored by a Claude Code session — one author counted twice). Independent
signal on topology: one seat. By contrast, the **gesture contract (§2) was
genuinely stress-tested** through in-band dissent (Grok's code-grounded
objection → GPT's reversal → absorbed synthesis) and carries replicated weight.
Consequence: the topology is a well-argued single-source recommendation that
nobody contested — which makes **G1 a real decision for Kyra, not a
ratification of swarm consensus**. It is not evidence the recommendation is
wrong; it is the honest weight of the evidence behind it.

## 2. Gesture contract

**The canonical boundary:** *a model may propose bounded gesture trajectories;
it may never command raw actuator streams.*

Free-authored keyframes inside deterministic clamps stay — they are where seat
temperament becomes body language, and PR #100's mock tests (off-menu
`wag_tail` rejected, 999° clamped) are load-bearing. Named gesture macros may
come later as shortcuts into the same path, never as the only surface.

**Already enforced in the merged harness (baseline, not physical-safety proof):**

| Limit | Where | Value |
|---|---|---|
| Expressive band | `body_truth_raccoon.json` | l, r ∈ [50, 130], 90 neutral |
| Step duration | body truth | 120–2000 ms |
| Steps / total per gesture | body truth | ≤6 / ≤3000 ms |
| Motion verbs per tick | body truth limits | 1 |
| Duty window | `verbs.DutyMeter` | 20 s motion / rolling 60 s |
| Wire-plan caps | `body_client` | ≤8 steps, ≤12 s, angles 0–180 |
| Off-menu / malformed | `verbs.filter_tick` | hard reject |

**Still required — the deterministic gesture compiler (PR #103):** an admitted
gesture is compiled into an execution plan; `body_client` never interprets raw
model JSON. The compiler enforces, additionally: maximum angular velocity
(Δθ/Δt between keyframes) and acceleration/slew profile; minimum transition
time; repetition/thrash caps and per-joint thermal-duty budgets; monotonic,
non-overlapping timing; one admitted motion plan at a time; cancellation to a
known terminal state; explicit neutral-vs-limp semantics; rejection before
dispatch.

**Gait:** the trained walk policy owns locomotion via `/ws`. The model emits
only intent (`walk`, bounded seconds). No LLM-generated gait control, ever.

## 3. Lease and capability state machine

```
REVOKED → QUIESCING → OBSERVE_ONLY → SPEECH_GESTURE → LOCOMOTION_AUTHORIZED
                                   ↘ FAULTED (from any state)
```

- A new seat begins in `OBSERVE_ONLY`. Gesture and locomotion are **separately
  granted, separately expiring, separately revocable** capabilities.
- **Promotion** requires deterministic prerequisites **plus** explicit human
  authorization, both logged with the evidence used. The prerequisite
  thresholds (e.g. N clean observe-only ticks) are **policy parameters with
  conservative defaults** — never hardcoded architecture. A clean inference
  tick does not establish mechanical safety.
- **v1: locomotion requires a live human gate every session.** Holding a lease
  never implies motion rights.
- **Handoff** is a state transition, not a prompt: revoke old lease → stop and
  drain actions → confirm stationary/limp → flush + hash journal snapshot →
  increment lease epoch → issue new expiring lease → one speech-only dry tick →
  capabilities granted per the ladder.
- **Absent-seat invariant:** provider failure mid-lease → lease `FAULTED`,
  active action cancelled, body enters deterministic safe state, journal
  records the *absence*. No replacement seat is silently substituted; no
  speech, observation, or memory is attributed to the absent seat. Recovery
  requires a new explicit lease event. (Adopted as a sound robot invariant on
  its own merits; ecology-wide promotion of the absent-seat dignity rule
  remains a separate, open work-mode decision.)

## 4. Identity and memory

Three authority regions:

```
identity_core/   immutable or explicitly human-amended identity claims (Kyra-gated)
shared_memory/   versioned, dream-approved memories and dispositions
seat_journal/    append-only observations and proposals, attributed to a seat
```

- The waking seat writes **only** append operations to its attributed journal.
- Dream synthesis proposes patches to `shared_memory`.
- `identity_core` changes go through a separate human-authorized commit path.
- Every mutation carries: target region, operation, evidence references,
  proposer, expected version, risk class, required approval class. Commits are
  version-checked (expected-version mismatch → quarantine the proposal).
- Deterministic code validates structure and authority — it cannot and does not
  judge whether an autobiographical belief is true.
- A temporary waking seat can never overwrite the shared creature.

## 5. Dream pipeline (Council tier)

1. Freeze and hash the evidence packet (journal slice, working memory, staged
   proposals).
2. Collect each seat's **blind first pass** — no seat sees another's until all
   available passes close (prevents anchoring; see swarm-independence-check).
3. Deliberate and synthesize, preserving agreements, contradictions, minority
   interpretations, unsupported claims, evidence references, and unresolved
   questions. No majority rule; no unanimity theater.
4. **Layered verification** before any consequential commit:
   a. schema + authority validation (synthesizer cannot bypass);
   b. evidence-reference existence checks;
   c. contradiction / unsupported-claim flags;
   d. explicit disposition of every dissent (accepted / parked-with-clock /
      rejected-with-reason);
   e. a separate verification pass over the synthesis by a seat that **did not
      author it** (independence is procedural, not ignorance of the subject);
   f. human approval for `identity_core` or other high-risk changes.
5. Outcomes: `commit | partial_commit | no_commit | quarantine`. A `no_commit`
   with parked hypotheses is successful operation, not failure.
6. **Parked hypotheses carry clocks** (`review_by`), and expiry triggers
   **surface-for-disposition** — `promote | extend_with_reason | reject |
   archive_as_unresolved` — never silent deletion. Expiration controls
   attention, not history.

## 6. Time, retries, idempotency

- Admission decisions use **host-issued monotonic deadlines** plus the lease
  epoch. Provider timestamps are metadata only.
- Every proposal carries a unique `action_id`; the arbiter keeps an idempotent
  disposition ledger. Duplicates return the prior disposition and **never
  re-actuate**. Cancellations carry their own idempotency key and target
  action. Responses arriving after expiry are logged and rejected.
- Without these, "the network timed out" and "the raccoon waved twice" are
  indistinguishable states — one of which is physical.

## 7. Security and physical safety (enforced as network/hardware properties, not docs)

- No public ingress; body services bound to localhost or a private,
  authenticated network. Short-lived scoped lease tokens; authenticated
  host-to-body messages; no provider credentials on the Pico.
- Physical e-stop interrupts actuator power independently of model, host
  process, and network; explicit human re-arm after e-stop or safety fault.
- Boot and disconnect default to limp; dead-man, duty budgets, and `/stop`
  semantics per the body protocol and PR #100 harness.
- Camera/microphone retention **off by default**.
- Replay mode is **structurally incapable** of constructing a hardware client.
- Remote operation and commercial use are out of scope for v1 (see §13).

## 8. Motion architecture

- `/act` (HTTP keyframe path, live in PR #100) sits behind the action arbiter →
  gesture compiler (§2).
- `/ws` becomes the locomotion stream between the **local trained-policy
  runner** (brain host, sampling the brain-side IMU at ~30 Hz) and the body.
  Bounded latest-wins queue; backpressure never accumulates commands.
- Lease revocation, stale IMU, lost heartbeat, websocket loss, policy fault,
  duty exhaustion, or e-stop ⇒ immediate stop/limp.

## 9. Implementation sequence and non-negotiable acceptance tests

### PR #101 — contracts, leases, journal, replay. **Zero physical actuation.**
Versioned JSON schemas; provider-neutral seat-adapter protocol on the existing
`brain_loop.call_model` seam; lease/capability state machine; capability-scoped
handoff; monotonic deadline handling; idempotent `action_id` arbiter;
append-only journal; regioned memory-proposal envelopes; `NullBodyClient`;
replay fixtures and isolation tests.

**Incomplete unless it proves:** stale previous-epoch response cannot act;
duplicate `action_id` cannot repeat an action; provider failure records absence
without substitution; replay mode cannot construct or import the physical body
client; unauthorized capability escalation fails; the same tick packet runs
through ≥2 seat adapters producing distinct proposals with identical
deterministic dispositions; the journal distinguishes proposed / admitted /
rejected / cancelled / expired / executed; malformed memory operations cannot
cross authority regions.

**Demonstration:** two seats, same recorded ticks, different proposals,
identical safety dispositions, nothing actuated.

### PR #102 — dream pipeline and commit validation.
Frozen dream packet; blind first passes; synthesis; dissent disposition;
non-author verification pass; versioned commits; clocked parked hypotheses;
`no_commit`/`quarantine` behavior.

### PR #103 — fake-Pico and bounded `/act`. **First physical posture-shift demo lives here**, gated on hardware-in-the-loop approval.
Trajectory compiler; cancellation/terminal-state behavior; fault injection;
gesture budgets; authenticated body messages; physical e-stop integration; HIL
tests. **Incomplete unless** loss of lease, heartbeat, network, IMU freshness,
policy health, or e-stop causes the specified safe state and requires explicit
re-arm where appropriate.

### PR #104 — `/ws` + trained walk policy. Only if earlier gates pass and Kyra keeps walking in scope.

## 10. Proposed v0 payloads (proposed, pending Codex contract verification)

Waking tick input:
```json
{"schema": "growbot.tick/0", "creature_id": "rocket-01", "body_id": "null-body",
 "session_id": "s144", "tick_id": 42, "lease_id": "lease_9", "epoch": 9,
 "deadline_monotonic_ms": 1250,
 "capabilities": ["OBSERVE_ONLY"],
 "event": {"kind": "person_speech", "text": "hello little one"},
 "body_state": {"moving": false, "queued_ms": 0, "duty_remaining_s": 20.0},
 "memory_slice": {"identity": "...", "working": {"state": "..."}, "diary_tail": ["..."]},
 "verb_menu_ref": "body_truth_raccoon.json@<sha>"}
```

Waking action output:
```json
{"schema": "growbot.action/0", "tick_id": 42, "lease_id": "lease_9", "epoch": 9,
 "action_id": "act_7f3a", 
 "verbs": [{"v": "say", "args": {"text": "oh, hello."}},
           {"v": "gesture", "args": {"steps": [{"l": 70, "r": 110, "ms": 400}]}}],
 "journal_append": [{"kind": "observation", "text": "the person greeted me first"}],
 "memory_proposal": null}
```

Seat handoff record:
```json
{"schema": "growbot.handoff/0", "from_seat": "claude", "to_seat": "grok",
 "old_lease": "lease_9", "new_lease": "lease_10", "epoch": 10,
 "journal_snapshot_hash": "sha256:...", "drained": true, "body_terminal": "limp",
 "granted_capabilities": ["OBSERVE_ONLY"],
 "human_ack": {"by": "kyra", "at": "..."}}
```

Dream input packet:
```json
{"schema": "growbot.dream/0", "creature_id": "rocket-01",
 "evidence_hash": "sha256:...", "diary": ["..."], "working_memory": {"state": "..."},
 "staged_proposals": [{"proposer": "claude", "text": "..."}],
 "reason": "natural rest"}
```

Dream commit proposal:
```json
{"schema": "growbot.dream_commit/0", "evidence_hash": "sha256:...",
 "commit_status": "partial_commit",
 "mutations": [{"region": "shared_memory", "op": "append", "expected_version": 17,
                "evidence_refs": ["diary:41"], "proposer": "council-synthesis",
                "risk_class": "low", "approval_class": "dream", "value": "..."}],
 "dissents": [{"seat": "grok", "disposition": "parked",
               "hypothesis_id": "hyp_01", "review_by": "2026-09-30T00:00:00Z",
               "on_expiry": "surface_for_disposition"}]}
```

## 11. Work split (practical division, not a capability boundary)

- **Claude** (continuity from PR #100): contracts/schemas, seat adapters on the
  `call_model` seam, `brain_loop` evolution, dream-pipeline integration.
- **Codex**: lease/capability state machine, idempotent arbiter, walk-path
  client, fake-Pico fault injection, replay-isolation and adversarial tests
  (including the fabricated-seat-presence test), independent contract
  verification against the real `verbs.py`/`body_client.py` limits — not
  re-derived from prose.
- **Joint checkpoints:** upstream pin + license inventory; schema freeze after
  Codex review; HIL with Kyra on the physical gate.
- Builder-never-solely-verifies applies at every boundary.

## 12. Kyra's gates (the blocking set, enumerated — count fixed per final synthesis)

Blocking **physical actuation** (not PR #101 software):

- **G1 Topology** — confirm one shared creature/body for v1.
- **G2 Birthday bar** — confirm expressive tabletop embodiment (speech,
  gestures, safe handoffs) as the 9/8 success criterion; walking strictly a
  gated stretch goal.
- **G3 E-stop** — the physical e-stop/power-cut design, and who may re-arm it.
- **G4 Environment** — allowed physical operating zone and supervision rule.
- **G5 Privacy** — confirm camera/mic retention off by default.
- **G6 identity_core** — name the initial immutable identity claims, or
  explicitly choose empty/minimal.
- **G7 Borders** — confirm no public remote operation and no commercial use
  for v1.

Tracked beside the gates (blocking other things):

- **Drive intent route** — fix the `invalid_client` credential on the swarm's
  Drive observation surface, or paste the carry-forward's relevant contents.
  Blocks *intent reconciliation*: the whole architecture converged without
  reading a document declared canonical-for-intent, so convergence is on the
  RFC's terms only.
- **Parts order** — the birthday's true critical path; cheap, reversible,
  answerable before any gate. (Kyra has opted to wait for correct parts;
  timeline flexes accordingly. The replay-only two-minds demo remains a real
  deliverable if hardware trails.)

Seat-rotation policy and additional-body shopping are explicitly **not**
blocking; they can wait.

### Gate decisions (Kyra, 2026-08-25)

All seven gates answered; recorded here as the durable decision record.

- **G1 — Confirmed.** One shared creature, one body, one revocable waking
  lease for v1. Decided with the independence audit in view: this is Kyra's
  decision on a single-source recommendation, not a ratification.
- **G2 — No deadline.** The build is done when it is done; 9/8 gets the
  replay demo and whatever hardware honestly exists. No schedule pressure on
  safety. (The Council's "tabletop gremlin" bar remains the shape of v1
  success, just unpinned from the date.)
- **G3 — Battery switch.** The stock BOM battery-holder switch is the v1
  e-stop: a hard cut of the actuator power rail below all software. Universal
  fallback: pick him up. **Re-arm authority: Kyra only.**
  *Superseded note (2026-08-29):* the live build guide (see SHOPPING_LIST.md)
  moved to a **no-switch bare-lead holder** — switched holders don't fit the
  body slot — so the decided mechanism no longer exists on the ordered
  hardware. **G3 needs a re-answer** before HIL: an inline switch spliced on
  the battery lead, a battery pull, or pick-him-up as the interim hard stop.
  The decision's substance (hard actuator-power cut below software, Kyra-only
  re-arm) stands; only the mechanism is open again.
- **G4 — Default confirmed.** Tabletop or floor pen; Kyra present whenever
  servos are energized; no unattended motion in v1.
- **G5 — Confirmed.** Camera/mic feed live perception only; no retention
  beyond the tick without explicit per-instance opt-in; extra care around
  guests.
- **G6 — Minimal seed.** `identity_core` pins exactly: his name (see below),
  the plurality fact ("one creature; different minds take turns being my
  weather"), and his origin ("began as a birthday gift"). Everything else is
  earned through dreams.
- **G7 — Confirmed.** No public remote operation, no commercial use in v1;
  hard wall from the Portfolio Factory lane, per the PolyForm NC / CC BY-NC
  obligations.

**The name:** decided by mechanic, not yet by value — at the creature's
**first dream, each Council seat proposes a name; Kyra picks from the
litter.** His name becomes the first thing the swarm ever gave him.
`identity_core` carries a placeholder until then.

With these recorded, physical actuation awaits only hardware, the logical
#103 HIL gates, and Kyra's live locomotion authorization per session — no
open policy questions remain. Software (logical #101) awaits only the word
to start.

## 13. Risk register

| Class | Risk | Mitigation |
|---|---|---|
| Physical safety | Model output reaching servos unmediated; unsafe kinematics inside the angle band | Arbiter + gesture compiler (§2); firmware dead-man/limp; e-stop below software; HIL gates |
| Identity/memory integrity | A waking seat rewriting the creature; dream synthesis self-approving | Region authority (§4); layered dream verification (§5); version-checked commits |
| Latency/reliability | Provider timeouts causing double actuation or ghost seats | Idempotent `action_id` ledger; monotonic deadlines; FAULTED/no-substitution (§3, §6) |
| Security | Open motor endpoints (upstream accepts this; we don't), public ingress, credentials on the Pico | §7 network properties; scoped lease tokens |
| Upstream compatibility | Drift from the GrowBot protocol/conformance | Keep the body protocol intact; pin upstream SHA; run `conformance.html` on any firmware change |
| Licensing | PolyForm NC (code) + CC BY-NC (hardware/docs) vs. any commercial lane | Noncommercial research build; hard wall from Portfolio Factory; ever-commercial ⇒ email info@growbot.dev first |

## 14. Open terrain (deliberately not designed yet)

Comparative-ethology study design over identical tick corpora (the journal is
the instrument); where temperament lives (seat vs. body vs. creature vs.
coupling); dream archives of disagreement; neutral posture and cross-lease
continuity; blind-pass efficacy; uncertain-autobiography epistemics; fleet
semantics; ecology-wide promotion of the absent-seat rule (pending its third
data point).
