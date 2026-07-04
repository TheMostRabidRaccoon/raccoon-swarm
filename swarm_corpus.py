"""Session corpus miner — research as exhaust.

Every session close emits a structured, SHA-anchored event record: who
participated, what governance signals fired (directives + phantom / honest-verb
violations), and mechanical interaction proxies (disagreement / convergence
keyword counts). It appends to a growing corpus so dataset collection (Paper 2)
is a byproduct of living, not a hand-fed chore — the "sky is the limit" half the
Session-132 daisy chain dropped, built as a closer hook.

Two disciplines carried in from the scorecard work:

- **Mechanical only.** Every field is a count or tag derived from what actually
  happened. Interaction figures are labelled PROXY (keyword heuristics) — never
  presented as ground-truth "dissent". No vibes on the scorecard; none in the
  corpus either.
- **SHA-anchored.** Each record carries the repo commit it was produced against,
  so a later claim ("the swarm converged on X in session N") is pinned to a
  state you can `git checkout` and re-verify — the pin-to-SHA lesson the
  meta-eval learned the hard way (a fact "verified against live main" is
  worthless once main moves).

Pure + stdlib. The closer injects the digest/scorecard and writes the file.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

CORPUS_VERSION = 1

# Keyword PROXIES for adversarial vs. concessive turns. Heuristics — they count
# a signal, they do not certify a dissent. Multi-word to cut false hits.
_DISSENT_MARKERS = (
    "i disagree", "i dissent", "i push back", "pushback", "push back",
    "you're wrong", "you are wrong", "that's wrong", "that is wrong",
    "i object", "i reject", "against the prior", "not accurate", "malpractice",
    "is inflated", "half-right", "is false", "empirically false", "overclaim",
)
_CONVERGENCE_MARKERS = (
    "i agree", "agreed", "i concur", "conceded", "i concede", "you're right",
    "you are right", "fair point", "i endorse", "i'll sign", "ratify",
    "converge", "correct on", "you win", "conceding",
)


def _count(text: str, markers: tuple) -> int:
    low = (text or "").lower()
    return sum(low.count(m) for m in markers)


def resolve_repo_sha() -> "str | None":
    """Best-effort short SHA of the repo this code lives in. RRI_REPO_SHA
    overrides (useful in a container where git isn't on PATH). Never raises."""
    env = os.environ.get("RRI_REPO_SHA")
    if env:
        return env.strip()[:12]
    try:
        here = Path(__file__).resolve().parent
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5)
        sha = out.stdout.strip()
        return sha or None
    except Exception:
        return None


def interaction_proxies(all_rounds: list) -> dict:
    """Per-round disagreement/convergence keyword counts. Labelled PROXY: a
    keyword heuristic over model outputs, not a semantic dissent detector."""
    per_round = []
    total_d = total_c = 0
    for i, rd in enumerate(all_rounds or []):
        d = c = 0
        models = []
        for m, out in (rd or {}).items():
            if m == "_meta" or not isinstance(out, str):
                continue
            models.append(m)
            d += _count(out, _DISSENT_MARKERS)
            c += _count(out, _CONVERGENCE_MARKERS)
        per_round.append({"round": i + 1, "models": sorted(models),
                          "dissent": d, "convergence": c})
        total_d += d
        total_c += c
    return {"method": "keyword-proxy",
            "dissent_markers": total_d,
            "convergence_markers": total_c,
            "per_round": per_round}


def build_corpus_event(*, session_id: "str | None", query: str,
                       all_rounds: list, digest: dict, scorecard: dict,
                       repo_sha: "str | None" = None,
                       generated_at: str = "") -> dict:
    """Map a closed session to one corpus record (pure). Governance figures are
    read straight from the scorecard (already the mechanical source of truth);
    interaction figures are keyword proxies, clearly namespaced."""
    fs = (scorecard or {}).get("filestore", {})
    return {
        "corpus_version": CORPUS_VERSION,
        "session_id": session_id,
        "generated_at": generated_at or datetime.now().isoformat(timespec="seconds"),
        # The anchor: which repo state produced this. A claim about this session
        # is checkable only against this commit.
        "repo_sha": repo_sha,
        "query": (query or "")[:200],
        "rounds": len((all_rounds or [])),
        "models_active": sorted({m for r in (all_rounds or [])
                                 for m in (r or {}) if m != "_meta"}),
        # Governance signals — the mechanical, ground-truth half.
        "governance": {
            "phantom_write_claims": fs.get("phantom_write_claims"),
            "phantom_paths": fs.get("phantom_paths", []),
            "honest_verb_violations": fs.get("honest_verb_violations"),
            "honest_verb_violation_paths": fs.get("honest_verb_violation_paths", []),
            "blockers": len(digest.get("blockers") or []),
            "reviews": len(digest.get("reviews") or []),
            "flags": len(digest.get("flags") or []),
            "emails_sent": len(digest.get("mail_sent") or []),
        },
        # Interaction PROXIES — keyword heuristics, not ground truth.
        "interaction_proxies": interaction_proxies(all_rounds),
        "writes": {
            "writes": len(digest.get("fs_writes") or []),
            "appends": len(digest.get("fs_appends") or []),
            "rejected": len(digest.get("fs_rejected") or []),
        },
        "truncated_models": digest.get("truncated_models") or [],
        "rate_limited_models": digest.get("rate_limited_models") or [],
    }
