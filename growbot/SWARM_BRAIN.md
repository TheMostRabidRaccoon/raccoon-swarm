# The swarm brain — letting the Council run him

GrowBot's mind is already two-tier, and the split is exactly the swarm's shape:

| Tier | Cadence | Job | Who fits |
|---|---|---|---|
| **Waking loop** | one model call per tick, seconds | perceive → emit verbs → move the body | **one seat at a time** |
| **Dream** | rare, slow, reflective | consolidate the diary, edit identity (code-clamped), set long-arc wants | **the Council** |

A robot tick has a hard latency budget — a body mid-gesture cannot wait minutes for
five models to deliberate. So the swarm does not vote on servo angles. One seat
drives the body in real time; the ecology's cognition enters where GrowBot's own
design already put slow thought: the dream.

## Waking seat

- Exactly one model holds the waking seat for a session. It receives the tick
  events, the working memory, the diary slice, and the verb menu, and answers in
  the harness's verbs-JSON contract (see `harness/brain_loop.py`).
- The seat is a *role*, not a fixture — any Council member can hold it, and handing
  it over between sessions is itself an experiment worth logging. Different seats
  will move him differently; the diary will show it.
- The seat's output is untrusted by construction: off-menu verbs are rejected,
  angles clamped, motion budgeted, duty-windowed. The validator does not care which
  model is talking.

## Dream tier = Council session

When he sleeps, the consolidation pass becomes a swarm deliberation:

1. **Inputs:** the episodic diary since last sleep, working-memory state, any staged
   `identity_proposal` from the waking seat (judged as data, not obeyed), and the
   waking seat's own account of the session.
2. **Deliberation:** seats read the same record and argue what it *meant* — what he
   learned, what to want next, what tomorrow's try should be. This is a normal
   Council round; the existing dispatch/deliberation machinery applies.
3. **Commit:** the round's synthesis is emitted in the dream-JSON contract
   (`identity_add` / `identity_drop` / `wants` / `tomorrow_try` / `longing`), and
   **code disposes**: patches clamped to ±1 sentence, identity hard-capped, longing
   drift rate-limited. The Council proposes; the clamp decides. Same rule upstream
   applies to a single model — five models get no more authority than one.
4. **Independence check:** before a dream commit is treated as Council consensus,
   the swarm-independence-check discipline applies — five seats agreeing after
   reading each other is one opinion, not five.

## Memory mapping

| GrowBot region | Writer (upstream rule) | Swarm counterpart |
|---|---|---|
| constitution + safety floor | nobody (engine-owned) | stays engine-owned — not a seat, not the Council, not Kyra-by-prompt |
| identity | the dream only | Council dream round, clamped in code |
| long-arc wants | the dream only | Council dream round |
| working memory (state/mood/rules) | waking loop | waking seat |
| episodic log | waking loop, append-only, earned slots only | waking seat; mirrored into the swarm filestore so the whole ecology can read his life |

The soul file (`memory.json`) stays the single source of truth on the brain host;
the filestore gets read-mirrors, not write access. One writer per region is the
whole discipline — the swarm reads everything and writes through exactly the two
sanctioned funnels (waking seat ticks, dream commits).

## Hard boundaries (unchanged by any of this)

- Firmware dead-man, `/stop`, boot-limp, release-means-limp: physical safety lives
  below the brain and no brain configuration touches it.
- The duty budget (20 s motion per rolling 60 s) is enforced in our harness code,
  not in any prompt.
- Kyra remains the hard gate for anything with real-world consequence beyond the
  desk — as with merges and credentials, operational asymmetry is a property of the
  environment, not a cognitive hierarchy.

## Phasing

- **4a — single brain.** `brain_loop.py` with one model (the repo's Claude adapter
  is the natural first driver). Prove ticks, verbs, memory, dream against the real
  body.
- **4b — Council dreams.** Route the dream pass through a swarm deliberation round;
  waking stays single-seat. This is the first moment the Council genuinely runs him.
- **4c — rotating waking seat.** Different seats take waking duty across sessions;
  compare temperaments via the diary. (The body doesn't change; only the mind does.
  That is the platform's whole design bet, and it's ours too.)
