# GrowBot × Raccoon Swarm 🦝🤖

A raccoon-bodied [GrowBot](https://github.com/britcruise9/GrowBot) whose brain can
eventually be the Council.

GrowBot (by Brit Cruise / [Art of the Problem](https://www.youtube.com/@ArtOfTheProblem))
is an open, ~$30 robot platform: a phone or computer is the brain, and the body is a
Raspberry Pi Pico 2 W, two servo legs, and a battery. The brain talks to the body over
an open Wi-Fi protocol; any brain that speaks the protocol can drive any body that
implements it. That open seam is what this project plugs into.

## The plan

| Phase | What | Status |
|---|---|---|
| 0 | Study upstream: protocol, firmware, agent-harness, walk policy | done — see notes below |
| 1 | Order the correct parts ([SHOPPING_LIST.md](SHOPPING_LIST.md)); print/remix the body ([RACCOON_BODY.md](RACCOON_BODY.md)) | waiting on parts; Kyra owns the order |
| 2 | Software harness: body client + verb contract + tick loop, runnable in mock mode with no hardware | merged in [PR #100](https://github.com/TheMostRabidRaccoon/raccoon-swarm/pull/100); mock path available now |
| 3 | Council embodiment baseline: topology, bounded gestures, leases/capabilities, memory regions, dream verification, gates, and work split ([EMBODIMENT_RFC.md](EMBODIMENT_RFC.md)) | draft [PR #101](https://github.com/TheMostRabidRaccoon/raccoon-swarm/pull/101); G1–G7 decided and recorded; implementation/integration/verification remain |
| 4A | Contracts + replay: schemas/adapters, leases, arbiter, journal, replay isolation (RFC logical #101) | implemented in draft PR #101; full repository suite green; **zero physical actuation** |
| 4B | Council dream pipeline + validated memory commits (RFC logical #102; [SWARM_BRAIN.md](SWARM_BRAIN.md)) | implemented — `harness/dream.py`: frozen packets, blind passes, layered verification, human gate, clocked parking; naming-dream rehearsal via `python3 growbot/harness/dream.py --demo` |
| 4C | Fake-Pico, bounded `/act`, conformance, and first hardware-in-the-loop posture shift (RFC logical #103) | waiting on correct hardware, HIL approval, and G1–G7 |
| 4D | `/ws` + trained walking policy (RFC logical #104) | gated stretch; only after earlier gates pass and Kyra keeps walking in scope |
| 5 | Multiple bodies / one body per model | deliberately deferred until one body is trustworthy |

> **Numbering note:** PR #101 is the actual draft RFC. Its logical #101–#104
> labels describe dependency order; they do not reserve future GitHub PR numbers.
> Parts and the Drive credential are tracked beside G1–G7, not counted as extra
> operational gates.

## What's here

| | |
|---|---|
| [SHOPPING_LIST.md](SHOPPING_LIST.md) | parts to order, with the gotchas that catch everyone |
| [RACCOON_BODY.md](RACCOON_BODY.md) | constraints + ideas for remixing the printed body into a raccoon |
| [SWARM_BRAIN.md](SWARM_BRAIN.md) | how the Council maps onto GrowBot's two-tier mind |
| [EMBODIMENT_RFC.md](EMBODIMENT_RFC.md) | the Council-recommended engineering baseline for whole-swarm embodiment (session 144) |
| [harness/](harness/) | brain-side harness: contracts, seats, leases, arbiter, journal, isolated replay, verb validator, and tick loop |

## Architecture in one picture

```
       waking loop (fast, one model, ~seconds)
  ┌──────────────────────────────────────────────┐
  │  event → prompt → verbs JSON → validate/clamp │
  │            → BodyClient → Pico → servo legs   │
  └──────────────┬───────────────────────────────┘
                 │ episodic log, staged identity proposals
                 ▼
       dream tier (slow, deliberative)             ← the Council lives here
  ┌──────────────────────────────────────────────┐
  │  consolidate diary → identity edits (clamped  │
  │  in code) → long-arc wants → tomorrow's try   │
  └──────────────────────────────────────────────┘
```

Upstream's core contract, which we keep intact:

> the agent emits verbs → body_truth defines the verbs → the actuator executes them

Off-menu verbs are rejected in code. Hard limits (angle bands, motion budgets, duty
windows, dead-man stops) are enforced by code and firmware, never by prompt text.
Whatever brain is plugged in — one model or five — the safety floor is engine-owned.

## Running the harness (no hardware needed)

```sh
python3 growbot/harness/brain_loop.py --mock --ticks 4
```

Mock mode proves the contract end-to-end: verbs validated and executed against a
console actuator, an off-menu verb rejected, out-of-range angles clamped, and a
closing dream pass. Point it at a real body later with `--body http://<pico-ip>`.

Tests live with the rest of the suite: `pytest tests/test_growbot_verbs.py tests/test_growbot_body_client.py`.

## Upstream, credit, and license

- Upstream repo: https://github.com/britcruise9/GrowBot — clone it next to this repo
  for firmware, STLs, walk policies, and the conformance test. We do not vendor it.
- The harness here is an original, independent implementation written against the
  published protocol spec (`protocol/PROTOCOL.md`) and body-truth format
  (`agent-harness/SPEC-BODY-TRUTH.md`), for interoperability.
- Upstream licensing: code PolyForm Noncommercial 1.0.0; hardware and docs
  CC BY-NC 4.0, credit Art of the Problem. This build is a noncommercial research
  project. If any of it ever heads toward commercial use, upstream asks you email
  info@growbot.dev first.

## Field notes from the study pass (phase 0)

- **The body is deliberately dumb.** Two motion paths: `/act` takes a short keyframe
  plan the chip glides through at 50 Hz (gestures); `/ws` streams poses at ~30 Hz
  (walking). The trained walk policy runs on the *brain* against the brain's IMU —
  the chip never stores a policy.
- **The mirror rule.** The two servos face outward, so the same angle swings the legs
  in opposite directions. To move both legs the same way, `l + r` must equal 180.
  `{l:90,r:90}` is neutral; `{l:50,r:130}` levers the body upright. Send that to
  check left/right without measuring anything.
- **Safety is layered and non-negotiable:** 500 ms dead-man limp on streamed control,
  release-means-limp, `/stop` is instant and hard, manual control clears queued plans,
  and the 20 s motion / rolling 60 s duty budget is enforced brain-side (our
  `DutyMeter`) because stock firmware doesn't enforce it.
- **LLMs author gestures well and gaits badly.** Expressive keyframe gestures are the
  generative path; locomotion goes through the trained policy, where the model only
  chooses *to travel* and for how long.
- **Hard servo gotcha:** standard 180° servos only. Continuous-rotation servos sell
  under near-identical names and read angles as speeds — legs that spin forever.
