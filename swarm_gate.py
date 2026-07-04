"""Session Quality Gate v0 — SCORE-ONLY. Records what it would have gated;
blocks nothing.

The Session-134 council converged on a gate (docs: Swarm Session Quality Gate
v1) and then converged again on shipping it measure-first: record gate
verdicts on the scorecard for real sessions, learn the false-positive rate,
and only then let mechanical checks graduate to blocking. This module is that
first step. It is deliberately mechanical-only:

- **M1 phantom claims** — paths claimed-as-written that don't exist on disk
  (the scorecard's persistence_gap, already existence-checked by the closer).
  Under the current machinery M1 and the Existence Criterion (the council's
  M3) are the same detector, so there is no separate M3 check here.
- **M2 honest-verb violations** — phantoms asserted with strong completion
  language ("written and verified", "read back"); a strict subset of M1.
- **Purpose tag** — gated sessions declare [SESSION_PURPOSE: <purpose>] in
  the query (gate spec §1). Absent tag is recorded as `unpurposed-session`.
  Expect every pre-gate session to fail this; that's telemetry, not a bug.
- **Friction trigger** (gate spec §5, mechanical half) — dissent proxy below
  floor AND few rounds → the session converged without visible friction.
  Routed as friction_required, NOT counted in gate_failures: frictionless
  consensus gets audited, it doesn't fail (the spec's own R4 rule).

Judgment checks (R1 genericity, R2 assumptions, R3 constraints, R5 next
action) are deferred by design — they belong to the dual-grader rubric, not
a keyword pass, and they must not punish anyone before their false-positive
rate is known. Same discipline as the scorecard: null/unmeasured is never
reported as pass.

Pure + stdlib. The closer computes this and embeds it in the scorecard.
"""
from __future__ import annotations

import re

GATE_VERSION = 0
GATE_MODE = "score-only"

# [SESSION_PURPOSE: portfolio-artifact] — gate spec §1. Matched anywhere in
# the query; the first tag wins.
_PURPOSE_RE = re.compile(r"\[SESSION_PURPOSE:\s*([a-z][a-z0-9-]*)\s*\]", re.IGNORECASE)

KNOWN_PURPOSES = (
    "research",
    "product-design",
    "code-review",
    "portfolio-artifact",
    "creative-production",
)

# Friction trigger floor (gate spec §5): mechanical, from the corpus record.
FRICTION_DISSENT_FLOOR = 2
FRICTION_MAX_ROUNDS = 2


def parse_purpose(query: str) -> "str | None":
    """Extract the declared session purpose, or None when untagged."""
    m = _PURPOSE_RE.search(query or "")
    return m.group(1).lower() if m else None


def evaluate_gate(*, scorecard: dict, corpus_event: "dict | None" = None,
                  query: str = "") -> dict:
    """Map a session's mechanical telemetry to a score-only gate verdict.

    Pure function. `scorecard` is the closer's build_scorecard output;
    `corpus_event` is swarm_corpus.build_corpus_event output (or None when
    corpus emission failed — friction then reports unmeasured, never a
    default verdict).
    """
    fs = (scorecard or {}).get("filestore", {})
    failures: list[str] = []
    unmeasured: list[str] = []

    # M1 — phantom write claims (existence is the gate; null = unmeasured)
    m1 = fs.get("phantom_write_claims")
    if m1 is None:
        unmeasured.append("M1")
    elif m1 > 0:
        failures.append("M1:phantom-claims")

    # M2 — honest-verb violations (subset of M1; same null discipline)
    m2 = fs.get("honest_verb_violations")
    if m2 is None:
        unmeasured.append("M2")
    elif m2 > 0:
        failures.append("M2:honest-verb-violations")

    # Purpose tag (spec §1)
    purpose = parse_purpose(query)
    if purpose is None:
        failures.append("unpurposed-session")
    elif purpose not in KNOWN_PURPOSES:
        failures.append(f"unknown-purpose:{purpose}")

    # Friction trigger (spec §5) — routed, not failed
    friction_required = False
    friction = {"status": "unmeasured", "dissent_markers": None,
                "rounds": scorecard.get("rounds") if scorecard else None,
                "floor": FRICTION_DISSENT_FLOOR}
    proxies = (corpus_event or {}).get("interaction_proxies") or {}
    dissent = proxies.get("dissent_markers")
    rounds = (scorecard or {}).get("rounds")
    if dissent is not None and rounds is not None:
        friction_required = (dissent < FRICTION_DISSENT_FLOOR
                             and rounds <= FRICTION_MAX_ROUNDS)
        friction = {"status": "ok", "dissent_markers": dissent,
                    "rounds": rounds, "floor": FRICTION_DISSENT_FLOOR}

    return {
        "gate_version": GATE_VERSION,
        "mode": GATE_MODE,
        "purpose": purpose,
        "gate_failures": failures,
        # Checks that could not run. NEVER folded into pass/fail — unknown is
        # not the same as none (scorecard discipline).
        "unmeasured": unmeasured,
        # What a blocking gate WOULD have done. This field is the measurement
        # the blocking decision is waiting on.
        "would_penalize": bool(failures),
        "friction_required": friction_required,
        "friction": friction,
        "deferred_checks": {
            "R1-genericity/R2-assumptions/R3-constraints/R5-next-action":
                "judgment checks — belong to the dual-grader rubric, "
                "measured before they ever punish",
            "M3-existence-criterion":
                "same detector as M1 under current machinery (claimed path "
                "must exist on disk); splits out only if decision-citation "
                "parsing lands",
        },
    }
