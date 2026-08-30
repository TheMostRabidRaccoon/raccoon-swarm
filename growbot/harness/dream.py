"""The dream tier: the Council consolidates; deterministic code disposes.

Logical #102 per growbot/EMBODIMENT_RFC.md §5. The dream is the creature's
sole identity writer, and this module is the machinery that makes a Council
deliberation safe to hold the pen:

  1. freeze — the evidence packet is hashed before anyone reads it
  2. blind first passes — each seat sees ONLY the frozen packet, never
     another seat's pass; an absent seat is recorded, never substituted
  3. synthesis — one named seat merges the passes into a commit proposal
  4. layered verification — schema/authority (contracts), evidence-ref
     existence, dissent-disposition coverage, a non-author verifier seat,
     version check, human gate for identity_core / high-risk mutations
  5. disposition — commit | partial_commit | no_commit | quarantine, with
     deterministic clamps on everything applied

Parked hypotheses carry clocks and SURFACE on expiry — promote, extend with
reason, reject, or archive as unresolved. Expiration controls attention, not
history: nothing is silently deleted.

No majority rule, no consensus theater: a no_commit with visible dissent is
successful operation. Stdlib only; zero imports from any actuation path.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass

if __package__ in (None, ""):
    import contracts  # pragma: no cover
else:
    from . import contracts

IDENTITY_CAP = 800
MIN_IDENTITY_AFTER_DROP = 40
SHARED_NOTES_CAP = 200
PARK_DISPOSITIONS = ("promote", "extend_with_reason", "reject", "archive_as_unresolved")


def freeze_evidence(mem, reason, *, creature_id="raccoon-01"):
    """Build and hash the frozen packet. The hash is what every pass, the
    synthesis, and the verifier are bound to — a dream about different
    evidence than its passes read is quarantined mechanically."""
    diary = tuple(f"diary:{i} {e['txt']}" for i, e in enumerate(mem.get("episodic_log", [])))
    pending = mem.get("working_memory", {}).get("pending_identity_proposal", "")
    staged = ({"proposer": "waking", "text": pending},) if pending else ()
    packet = contracts.DreamInput(
        creature_id=creature_id,
        evidence_hash="",  # filled after hashing the content below
        diary=diary,
        working_memory={"state": mem.get("working_memory", {}).get("state", ""),
                        "identity": mem.get("identity", "")},
        staged_proposals=staged,
        reason=reason,
    )
    content = packet.to_dict()
    del content["evidence_hash"]
    digest = "sha256:" + hashlib.sha256(
        json.dumps(content, sort_keys=True).encode()).hexdigest()
    return contracts.DreamInput(**{**packet.__dict__, "evidence_hash": digest})


def valid_evidence_refs(packet, passes):
    """The deterministic universe of citable evidence for this dream."""
    refs = {"state", "reason"}
    refs.update(f"diary:{i}" for i in range(len(packet.diary)))
    refs.update(f"pass:{p.seat}" for p in passes)
    if packet.staged_proposals:
        refs.add("staged:waking")
    return refs


@dataclass(frozen=True)
class DreamResult:
    outcome: str            # commit | partial_commit | no_commit | quarantine
    reason: str
    evidence_hash: str
    applied: tuple          # mutations actually committed
    held: tuple             # mutations awaiting the human gate
    absent_seats: tuple
    parked: tuple           # hypothesis_ids parked this dream


class DreamPipeline:
    """One dream cycle. Construction enforces the structural independence
    rule: the verifier may have filed a first pass, but never authored the
    synthesis it verifies."""

    def __init__(self, passes, synthesizer, verifier, *, clock=time.time):
        """passes: {seat_name: fn(packet_dict) -> dream_pass dict}
        synthesizer: (seat_name, fn(packet_dict, [pass_dicts]) -> commit dict)
        verifier: (seat_name, fn(packet_dict, commit_dict) -> {"approve": bool, "reason": str})
        """
        self.passes = dict(passes)
        self.synth_seat, self.synth_fn = synthesizer
        self.verify_seat, self.verify_fn = verifier
        if self.verify_seat == self.synth_seat:
            raise ValueError("the verifier must not be the synthesis author")
        self._clock = clock

    def run(self, mem, reason, *, human_ack=None, creature_id="raccoon-01"):
        packet = freeze_evidence(mem, reason, creature_id=creature_id)
        packet_dict = packet.to_dict()

        # blind first passes: each seat receives only the frozen packet
        first_passes, absent = [], []
        for seat, fn in self.passes.items():
            try:
                raw = fn(dict(packet_dict))
                if isinstance(raw, dict):
                    raw.setdefault("schema", contracts.SCHEMA_DREAM_PASS)
                    raw.setdefault("seat", seat)
                    raw.setdefault("evidence_hash", packet.evidence_hash)
                parsed = contracts.parse_dream_pass(raw)
                if parsed.seat != seat:
                    raise contracts.ContractError("a pass cannot speak for another seat")
                if parsed.evidence_hash != packet.evidence_hash:
                    raise contracts.ContractError("pass is bound to different evidence")
                first_passes.append(parsed)
            except Exception as exc:
                # absent-seat dignity: record the absence; substitute nobody
                absent.append({"seat": seat, "error": f"{type(exc).__name__}: {exc}"})

        if not first_passes:
            return self._finish(mem, packet, "quarantine",
                                "every seat was absent — no dream occurred",
                                absent=absent)

        # synthesis by one named seat, over the frozen packet + all passes
        try:
            raw_commit = self.synth_fn(dict(packet_dict), [p.to_dict() for p in first_passes])
            commit = contracts.parse_dream_commit(raw_commit)
        except Exception as exc:
            return self._finish(mem, packet, "quarantine",
                                f"synthesis failed validation: {exc}", absent=absent)

        # layered verification, in order; first hard failure quarantines
        why = self._verify(packet, first_passes, commit, mem)
        if why:
            return self._finish(mem, packet, "quarantine", why, absent=absent)

        approval = self.verify_fn(dict(packet_dict), commit.to_dict())
        if not isinstance(approval, dict) or not approval.get("approve"):
            reason_text = (approval or {}).get("reason", "no reason given") \
                if isinstance(approval, dict) else "malformed verifier reply"
            return self._finish(mem, packet, "quarantine",
                                f"verifier {self.verify_seat} withheld approval: {reason_text}",
                                absent=absent)

        # disposition: park clocked hypotheses, apply what clears the gates
        parked_ids = self._park_dissents(mem, commit)
        if commit.commit_status in ("no_commit", "quarantine"):
            return self._finish(mem, packet, commit.commit_status,
                                "the Council chose not to commit — that is success, not failure",
                                absent=absent, parked=parked_ids)

        applied, held = [], []
        for mutation in commit.mutations:
            if self._needs_human(mutation) and not human_ack:
                held.append(mutation)
            else:
                self._apply(mem, mutation, human_ack)
                applied.append(mutation)
        if applied:
            mem["memory_versions"]["shared_memory"] += 1
        mem["working_memory"]["pending_identity_proposal"] = ""

        outcome = "commit" if not held else "partial_commit"
        reason_text = "" if not held else f"{len(held)} mutation(s) held for the human gate"
        return self._finish(mem, packet, outcome, reason_text,
                            absent=absent, applied=applied, held=held, parked=parked_ids)

    # ── verification layers ──

    def _verify(self, packet, first_passes, commit, mem):
        if commit.evidence_hash != packet.evidence_hash:
            return "commit is bound to different evidence than this dream froze"
        refs = valid_evidence_refs(packet, first_passes)
        for m in commit.mutations:
            missing = [r for r in m.get("evidence_refs", []) if r not in refs]
            if missing:
                return f"mutation cites evidence that does not exist: {missing}"
            expected = m.get("expected_version")
            if expected != mem["memory_versions"]["shared_memory"]:
                return (f"version mismatch: mutation expects {expected}, "
                        f"shared_memory is at {mem['memory_versions']['shared_memory']}")
        disposed = {d.get("seat") for d in commit.dissents}
        undisposed = [p.seat for p in first_passes if p.concerns and p.seat not in disposed]
        if undisposed:
            return f"concerns filed without disposition: {undisposed}"
        return None

    @staticmethod
    def _needs_human(mutation):
        return (mutation.get("region") == "identity_core"
                or mutation.get("approval_class") == "human"
                or mutation.get("risk_class") == "high")

    # ── deterministic application (the clamps live here, not in prompts) ──

    def _apply(self, mem, mutation, human_ack):
        region, op = mutation["region"], mutation["op"]
        value = mutation.get("value")
        if region == "identity_core":
            if op != "amend" or not isinstance(value, dict):
                raise ValueError("identity_core supports only op=amend with an object value")
            core = mem["identity_core"]
            if "name" in value:
                core["name"] = str(value["name"])[:60]
            for claim in value.get("add_claims", []):
                claim = " ".join(str(claim).split())[:160]
                if claim and claim not in core["claims"]:
                    core["claims"].append(claim)
            core["claims"] = core["claims"][:8]
            core["last_amended_by"] = dict(human_ack)
        elif region == "shared_memory":
            if op == "append":
                line = " ".join(str(value).split())[:200]
                if line:
                    mem["shared_notes"].append(line)
                    del mem["shared_notes"][:-SHARED_NOTES_CAP]
            elif op == "identity_patch":
                patch = value if isinstance(value, dict) else {}
                mem["identity"] = _apply_identity_patch(
                    mem["identity"], patch.get("add", ""), patch.get("drop", ""))
            elif op == "set_wants":
                wants = value if isinstance(value, list) else []
                mem["goals"]["wants"] = [str(w)[:80] for w in wants[:4] if str(w).strip()]
            elif op == "set_next_try":
                mem["goals"]["next_try"] = " ".join(str(value).split())[:60]
            else:
                raise ValueError(f"unknown shared_memory op {op!r}")
        else:
            raise ValueError(f"the dream cannot write region {region!r}")

    def _park_dissents(self, mem, commit):
        parked_ids = []
        for d in commit.dissents:
            if d.get("disposition") != "parked":
                continue
            hyp_id = d.get("hypothesis_id") or f"hyp_{uuid.uuid4().hex[:8]}"
            mem["parked"].append({
                "hypothesis_id": hyp_id,
                "seat": d.get("seat", "unknown"),
                "text": d.get("text", ""),
                "review_by": d["review_by"],
                "on_expiry": "surface_for_disposition",
                "parked_at": self._clock(),
            })
            parked_ids.append(hyp_id)
        return parked_ids

    def _finish(self, mem, packet, outcome, reason, *, absent=(), applied=(), held=(), parked=()):
        mem.setdefault("dream_ledger", []).append({
            "t": self._clock(), "evidence_hash": packet.evidence_hash,
            "synthesizer": self.synth_seat, "verifier": self.verify_seat,
            "outcome": outcome, "reason": reason,
            "absent": [a["seat"] for a in absent],
            "applied": len(applied), "held": len(held), "parked": list(parked),
        })
        return DreamResult(outcome, reason, packet.evidence_hash,
                           tuple(applied), tuple(held),
                           tuple(a["seat"] for a in absent), tuple(parked))


def _apply_identity_patch(identity, add, drop):
    """The upstream clamp discipline: patch ±1 sentence, hard cap, never
    drop below a self, evict the oldest sentence past the cap."""
    drop = " ".join(str(drop or "").split()).rstrip(".!?")
    if drop:
        sentences = identity.replace(". ", ".\n").split("\n")
        kept = [s for s in sentences if s.strip().rstrip(".!?") != drop]
        candidate = " ".join(kept).strip()
        if len(candidate) >= MIN_IDENTITY_AFTER_DROP:
            identity = candidate
    add = " ".join(str(add or "").split())[:160]
    if add and add.rstrip(".!?") not in identity:
        identity = (identity + " " + add).strip()
    while len(identity) > IDENTITY_CAP:
        cut = identity.find(". ")
        identity = identity[cut + 2:].strip() if cut >= 0 else identity[-IDENTITY_CAP:]
    return identity


# ── parked-hypothesis attention clocks: surface, never silently forget ──

def _demo():  # pragma: no cover — a dress rehearsal of the first dream
    """Five mock seats dream over a tiny diary and each proposes a name.
    The identity_core amendment is held at the human gate: the pipeline
    surfaces the litter, and only Kyra's ack ever pins a name."""
    import copy
    from pathlib import Path

    mem = json.loads((Path(__file__).parent / "memory_seed.json").read_text())
    mem["episodic_log"] = [
        {"tick": 1, "txt": "I woke up and wiggled my legs for the first time."},
        {"tick": 2, "txt": "Kyra laughed and I decided that was a good sound."},
    ]
    proposals = {"claude": "Archive", "gpt": "Vector", "grok": "Havoc",
                 "gemini": "Lumen", "perplexity": "Query"}

    def make_pass(seat):
        def fn(packet):
            return {"proposal": {"name": proposals[seat],
                                 "why": f"{seat} heard the diary and thought of it"},
                    "concerns": []}
        return fn

    def synthesize(packet, passes):
        litter = ", ".join(f"{p['seat']}: {p['proposal']['name']}" for p in passes)
        return {"schema": contracts.SCHEMA_DREAM_COMMIT,
                "evidence_hash": packet["evidence_hash"],
                "commit_status": "commit",
                "mutations": [
                    {"region": "shared_memory", "op": "append",
                     "value": f"the Council proposed names: {litter}",
                     "expected_version": 0, "proposer": "council-synthesis",
                     "risk_class": "low", "approval_class": "dream",
                     "evidence_refs": [f"pass:{p['seat']}" for p in passes]},
                    {"region": "identity_core", "op": "amend",
                     "value": {"name": "<Kyra picks from the litter>"},
                     "expected_version": 0, "proposer": "council-synthesis",
                     "risk_class": "high", "approval_class": "human",
                     "evidence_refs": ["diary:1"]},
                ],
                "dissents": []}

    verify = lambda packet, commit: {"approve": True, "reason": "litter checks out"}
    pipe = DreamPipeline(passes={s: make_pass(s) for s in proposals},
                         synthesizer=("claude", synthesize),
                         verifier=("grok", verify))
    result = pipe.run(copy.deepcopy(mem), "the first dream — the naming")
    print("— the first dream (rehearsal) —")
    print(f"  outcome: {result.outcome} · {result.reason}")
    print(f"  evidence: {result.evidence_hash[:23]}…")
    for m in result.applied:
        print(f"  ✓ applied: {m['value']}")
    for m in result.held:
        print(f"  ✋ held for Kyra: {m['region']}.{m['op']} → {m['value']}")
    print("\n  the litter awaits its person. 🦝")


def surface_expired(mem, now_iso):
    """Return hypotheses whose review clock has passed. They stay parked
    until explicitly disposed — expiry controls attention, not history."""
    return [h for h in mem.get("parked", []) if h["review_by"] <= now_iso]


def dispose_parked(mem, hypothesis_id, disposition, *, reason="", new_review_by=None):
    if disposition not in PARK_DISPOSITIONS:
        raise ValueError(f"disposition must be one of {PARK_DISPOSITIONS}")
    for i, h in enumerate(mem.get("parked", [])):
        if h["hypothesis_id"] != hypothesis_id:
            continue
        if disposition == "extend_with_reason":
            if not new_review_by or not reason:
                raise ValueError("extension requires a new review_by and a reason")
            h["review_by"] = new_review_by
            h.setdefault("extensions", []).append(reason)
            return h
        record = {**mem["parked"].pop(i), "disposition": disposition, "reason": reason}
        mem["parked_archive"].append(record)  # the audit record survives
        return record
    raise KeyError(f"no parked hypothesis {hypothesis_id!r}")


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys
    if "--demo" in _sys.argv:
        _demo()
    else:
        print("usage: python3 growbot/harness/dream.py --demo")
