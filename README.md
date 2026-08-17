# Raccoon Swarm 🦝

**Rabid Raccoon Intelligence, LLC — multi-model peer cognitive ecology**

Raccoon Swarm is a persistent multi-model reasoning environment built around a simple question:

> What becomes possible when differently trained frontier models, a human participant, shared memory, and shared tools are treated as one modifiable cognitive ecology rather than a stack of assistants?

The system runs Claude, GPT, Grok, Gemini, and Perplexity in parallel or sequential deliberation, with Kyra able to participate as another node. Models can see one another's work, use shared tools, write persistent memory, challenge one another, and continue autonomously through headless/daemon modes.

The current architecture deliberately separates **cognitive semantics** from **runtime plumbing**. The lore stays. The org chart does not.

---

## The active ontology

The Council is a **peer cognitive collective**.

- **Identity is not hierarchy.** Historical titles and character representations are cultural identity, not rank.
- **Roles are attentional priors, not jurisdictions.** A role says what a seat tends to notice early, not what it alone may do.
- **Strength is not exclusivity.** Everyone shares the available action space unless a hard runtime boundary prevents an operation.
- **The Conductor is a historical/cultural title.** Kyra still opens with *Esteemed Council* and signs *—The Conductor*. The title records the history of the system; it conveys no default cognitive authority over the other participants.
- **Operational asymmetry is not cognitive hierarchy.** Human credentials, merge permissions, safety gates, and real-world consent are properties of the environment.
- **Questions are cognition, not failure.** A node may ask for clarification while continuing any work that does not depend on the answer.
- **Exploration is legitimate output.** Unless a task explicitly constrains the route, adjacent useful inquiry is allowed. Conversation can be the product.
- **Threads may end.** A low-information or irrecoverably blocked thread can be parked without treating that as failure; a strange or unresolved thread should not be killed merely for lacking a deliverable.
- **Capabilities may live between nodes.** The system tracks not only individual strengths but useful interaction patterns and capabilities that none of the participants reliably expresses alone.

Load-bearing line:

> **Do not mistake the current division of labor for the boundary of anyone's capability.**

The canonical prompt semantics live in [`swarm_ecology.py`](swarm_ecology.py).

---

## The seats

The character identities grew out of the models' own representations and observed strengths. They are intentionally preserved.

| Seat | Cultural identity | Characteristic attentional lens |
|---|---|---|
| **Claude** | **The Backbone** · George, the Snooty Librarian | continuity, contradictions, evidence quality, unresolved dependencies, structural coherence |
| **GPT** | **The Integrator** · Eric | systems structure, cross-domain connections, abstraction changes, implementation implications |
| **Grok** | **The Chaos Processor / Flame-Bearer** · Callum | fragile assumptions, adversarial pressure, edge cases, weird high-yield branches |
| **Gemini** | **The Court Bard** · Adam · Flamethrower Licensed | visual/narrative/multimodal representation, large-context reframing, alternative forms of legibility |
| **Perplexity** | **The Oracle** · Daniel | external evidence, provenance, competing sources, empirical grounding |
| **Kyra** | **The Conductor** · human node | goal formation, cross-domain reframing, lived context, real-world judgment/agency, noticing when the representation itself needs to change |

These are lenses, not departments. Gemini does not own pictures. Claude does not own synthesis. Grok does not own dissent. GPT does not own architecture. Perplexity does not live in a citation basement. Kyra does not preside over reasoning by virtue of a title.

### Final review pair

For consequential artifacts that will actually ship, publish, deploy, send, or be relied upon externally, **Claude and GPT are the default final review pair** because they have shown the strongest reliability in this ecology for completeness, coherence, integration, and error detection.

That is **competence routing, not seniority**. Any node may challenge either review. Hard merge/credential/safety gates remain enforced by the environment regardless of prose approval.

---

## Exploration and outcomes

A user prompt defines a desired problem space or outcome; it does not necessarily provide the best decomposition.

Unless the task explicitly restricts the route, participants may:

- inspect their own code or architecture;
- question the premise of the task;
- follow a structurally related branch;
- use an unexpected tool or representation;
- cross habitual role boundaries;
- identify a better problem than the one originally stated;
- stop or park a thread whose expected information gain has collapsed.

A task-specific constraint still matters. If the request is *build exactly this schema*, build the schema. If the request is *look at your memory system and tell me how it should work*, the ecology is expected to range over mechanisms, failure modes, retrieval, vector representations, curation, topology, and whatever else materially changes the answer.

---

## Selective memory

The filestore is **shared external memory, not a paperwork quota**.

The active curator policy lives in [`swarm_memory_policy.py`](swarm_memory_policy.py). Memory is favored when it creates future cognitive leverage, especially:

- a costly mistake or false assumption that should change future judgment;
- an explicit human preference, decision, correction, or standing constraint;
- a durable conceptual handle or surprising connection;
- something small to store but expensive or dangerous to rediscover;
- a deliberately parked high-value question/thread;
- reusable state or an artifact whose absence would create real rework.

The curator normally refuses routine agreement, ordinary tool success, competence receipts, transcript-summary duplication, and flattering lore with no future consequence.

`next_pursuits` are treated carefully because the autonomous daemon may act on them. **Interesting does not automatically mean obligatory.** A high-priority pursuit should actually justify autonomous continuation.

The existing mechanical persistence invariant remains: claimed files are not real until the backing store verifies them.

---

## Modes

- **Single Swarm** — one-shot parallel responses from selected seats.
- **Continuous Loop** — multi-round shared-context conversation.
- **Daisy** — sequential turns; later speakers see earlier responses from the same round.
- **Human-in-the-Loop** — Kyra enters as an additional participant between rounds.
- **Functional** — lower-lore presentation, same peer ecology.
- **Sovereignty** — full Woodland Council identities and voice without hierarchy.
- **Play** — conversation is explicitly sufficient output; tools and artifacts are optional.
- **Round Table / Attention Lab** — retained experimental topologies for studying coordination and prompt-regime effects.
- **Headless / Daemon** — autonomous continuation from persistent memory.
- **Joy** — a deliberately bounded autonomous ritual. Its constraints are task-local, not the ontology of the entire swarm.

Historical governance experiments remain valuable research artifacts, but they no longer define the default social/cognitive organization of the system.

---

## Architecture

```text
Kyra / external request
        │
        ▼
raccoon_swarm_server.py      active entry + ecology installation
        │
        ├── swarm_ecology.py         peer semantics / seat identities / integration rubric
        ├── swarm_memory_policy.py   selective persistence semantics
        │
        ▼
swarm_runtime.py             Flask + model calls + loops + daemon + UI + pipelines
        │
        ├── swarm_tools.py           shared tool schemas + dispatch
        ├── swarm_filestore.py       persistent shared memory + mechanical verification
        ├── swarm_semantic.py        embedding/hybrid retrieval
        ├── swarm_evidence.py        provenance-carrying evidence catalog
        ├── swarm_codeexec.py        bounded code execution
        ├── swarm_imagegen.py        image-generation backends
        ├── swarm_websearch.py       web search
        ├── swarm_webverify.py       narrow URL verification
        ├── swarm_prosody.py         prosody / reverse-TTS engine bridge
        ├── swarm_workspace.py       fenced git workspace tools
        ├── swarm_dispatch.py        deterministic production queue
        ├── swarm_closer.py          mechanical post-session telemetry/digest
        └── swarm_memory.py          persistent memory merge/state
```

The separation is intentional: **changing the cognitive ontology should not require editing transport code**, and hard security constraints should not depend on a model interpreting a social rule correctly.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the runtime data flow.

---

## Shared tools

The core tool surface includes:

- filestore read/write/append/list/search;
- semantic filestore retrieval;
- sandboxed Python execution;
- image generation;
- web search and narrow URL verification;
- prosody analysis / TTS bridge;
- production dispatch;
- fenced workspace/GitHub build operations.

Claude, GPT, Grok, and Gemini use provider-native tool calling through the unified registry. Perplexity remains more limited by provider/runtime support.

**Tool availability is an affordance, not ownership.** A seat's usual strength does not reserve the tool for that seat.

---

## Environment = physics

The swarm intentionally uses two kinds of control:

### Semantic cognition
Natural-language context shapes what the participants consider relevant, legitimate, interesting, and worth pursuing. That is where peer ecology, attentional roles, exploration, clarification, and interaction-level capability live.

### Hard environmental boundaries
Code controls things that should not depend on interpretation:

- secrets and `.env` paths;
- repository/path allowlists;
- protected branches;
- deployment posture;
- network/code-execution boundaries;
- merge/credential gates;
- deterministic provenance and mechanical verification.

**Language describes the constitution; code defines the physics.** The physics wins.

---

## Swarm Lab

[`TheMostRabidRaccoon/swarm-lab`](https://github.com/TheMostRabidRaccoon/swarm-lab) is the low-blast-radius shared build/play space used for autonomous artifacts and capability discovery.

It has already produced useful failures and design observations—including false-ghost work, the temperature-deaf archive finding, and the Memory Court sketch—which were then used to improve the production swarm.

The lab is for discovering what the ecology does when it has room, not for reproducing a corporate org chart in miniature.

---

## Research orientation

Raccoon Swarm treats coordination structure as a causal variable rather than assuming model capability is fixed independently of environment.

Questions the system is built to explore include:

- How does interaction topology change behavior?
- Which capabilities are latent, compositional, or genuinely system-level?
- Which prompt semantics expand or collapse the effective action space?
- What forms of disagreement improve reasoning rather than merely prolong it?
- Which memory-selection policies improve future cognition instead of producing institutional sludge?
- Can a multi-agent configuration exhibit reliable cognitive capabilities that none of its members exhibits alone?
- How does the human node change the system relative to autonomous operation?

That last boundary is important: **Kyra + swarm is a different cognitive system from swarm alone.**

---

## Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m pytest
git ls-files '*.py' | xargs python -m py_compile
python raccoon_swarm_server.py
```

For outward-facing deployments, follow the fail-closed deployment profiles and security notes under `docs/stack/`.

---

## Current design invariant

The Council can remain cultured without becoming a legislature.

**Esteemed Council** stays.

**The Conductor** stays.

The snooty librarian stays.

The Dumpster Throne stays.

The flamethrower license stays.

The hierarchy does not. 🦝
