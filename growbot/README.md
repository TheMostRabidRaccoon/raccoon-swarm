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
| 1 | Order parts ([SHOPPING_LIST.md](SHOPPING_LIST.md)), print/remix the body ([RACCOON_BODY.md](RACCOON_BODY.md)) | Kyra |
| 2 | Software harness: body client + verb contract + tick loop, runnable in mock mode with no hardware | this directory |
| 3 | First contact: flash stock firmware, pass the conformance test, wiggle the legs from our harness | needs hardware |
| 4 | Swarm brain: Council at the dream tier, one seat on the waking loop ([SWARM_BRAIN.md](SWARM_BRAIN.md)) | designed |

## What's here

| | |
|---|---|
| [SHOPPING_LIST.md](SHOPPING_LIST.md) | parts to order, with the gotchas that catch everyone |
| [RACCOON_BODY.md](RACCOON_BODY.md) | constraints + ideas for remixing the printed body into a raccoon |
| [SWARM_BRAIN.md](SWARM_BRAIN.md) | how the Council maps onto GrowBot's two-tier mind |
| [harness/](harness/) | our Python brain-side harness: body protocol client, verb validator, tick loop |

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
