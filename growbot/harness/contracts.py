"""Versioned message contracts for the embodiment stack (logical #101).

Executable form of the v0 payloads in growbot/EMBODIMENT_RFC.md §10, plus the
shared vocabulary (lease states, capabilities, journal states). This module is
Claude's package under the RFC §11 split; Codex verifies it independently and
builds the lease state machine and arbiter against it.

Boundary discipline: this module does STRUCTURAL validation only — required
fields, types, ranges, and authority rules that are contract-expressible (a
waking seat can never target identity_core). Admission logic — staleness
against monotonic deadlines, epoch matching, duplicate action_id dispositions,
capability enforcement — belongs to the deterministic arbiter (Codex's
package) and is intentionally absent here.

Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_TICK = "growbot.tick/0"
SCHEMA_ACTION = "growbot.action/0"
SCHEMA_HANDOFF = "growbot.handoff/0"
SCHEMA_DREAM = "growbot.dream/0"
SCHEMA_DREAM_PASS = "growbot.dream_pass/0"
SCHEMA_DREAM_COMMIT = "growbot.dream_commit/0"

# Lease/capability vocabulary (RFC §3). The transition rules live in Codex's
# state machine; the names are contract so every module speaks the same ones.
LEASE_STATES = (
    "REVOKED", "QUIESCING", "OBSERVE_ONLY", "SPEECH_GESTURE",
    "LOCOMOTION_AUTHORIZED", "FAULTED",
)
CAPABILITIES = ("OBSERVE_ONLY", "SPEECH_GESTURE", "LOCOMOTION_AUTHORIZED")

# Memory authority regions (RFC §4). The waking seat may append to its own
# journal; only the dream tier proposes shared_memory; identity_core is
# human-gated and unreachable from any waking action.
MEMORY_REGIONS = ("identity_core", "shared_memory", "seat_journal")

# Journal disposition vocabulary (RFC §9 acceptance tests). brain_loop emits
# proposed/admitted/rejected/executed today; cancelled/expired arrive with the
# arbiter.
JOURNAL_STATES = ("proposed", "admitted", "rejected", "cancelled", "expired", "executed")

DREAM_COMMIT_STATUSES = ("commit", "partial_commit", "no_commit", "quarantine")


class ContractError(ValueError):
    """A payload failed structural validation. `why` is human-readable."""

    def __init__(self, why):
        super().__init__(why)
        self.why = why


def _require(obj, name, kind, why_prefix):
    val = obj.get(name)
    if not isinstance(val, kind) or isinstance(val, bool) and kind is not bool:
        raise ContractError(f"{why_prefix}.{name} must be {getattr(kind, '__name__', kind)}")
    return val


def _require_schema(obj, expected):
    if not isinstance(obj, dict):
        raise ContractError("payload must be an object")
    if obj.get("schema") != expected:
        raise ContractError(f"schema must be {expected!r}, got {obj.get('schema')!r}")


@dataclass(frozen=True)
class TickInput:
    """What the waking seat perceives on one tick. Built by the harness."""
    creature_id: str
    body_id: str
    session_id: str
    tick_id: int
    lease_id: str
    epoch: int
    deadline_monotonic_ms: int
    capabilities: tuple
    event: dict
    body_state: dict
    memory_slice: dict
    verb_menu_ref: str
    schema: str = SCHEMA_TICK

    def to_dict(self):
        d = self.__dict__.copy()
        d["capabilities"] = list(self.capabilities)
        return d


def parse_tick_input(obj):
    _require_schema(obj, SCHEMA_TICK)
    caps = _require(obj, "capabilities", list, "tick")
    bad = [c for c in caps if c not in CAPABILITIES]
    if bad:
        raise ContractError(f"tick.capabilities has unknown entries {bad}")
    return TickInput(
        creature_id=_require(obj, "creature_id", str, "tick"),
        body_id=_require(obj, "body_id", str, "tick"),
        session_id=_require(obj, "session_id", str, "tick"),
        tick_id=_require(obj, "tick_id", int, "tick"),
        lease_id=_require(obj, "lease_id", str, "tick"),
        epoch=_require(obj, "epoch", int, "tick"),
        deadline_monotonic_ms=_require(obj, "deadline_monotonic_ms", int, "tick"),
        capabilities=tuple(caps),
        event=_require(obj, "event", dict, "tick"),
        body_state=_require(obj, "body_state", dict, "tick"),
        memory_slice=_require(obj, "memory_slice", dict, "tick"),
        verb_menu_ref=_require(obj, "verb_menu_ref", str, "tick"),
    )


@dataclass(frozen=True)
class ActionOutput:
    """What the waking seat proposes in reply to one tick."""
    tick_id: int
    lease_id: str
    epoch: int
    action_id: str
    verbs: tuple            # raw verb calls; semantic validation is verbs.filter_tick's job
    journal_append: tuple   # seat-attributed observations, append-only
    memory_proposal: dict | None
    schema: str = SCHEMA_ACTION

    def to_dict(self):
        d = self.__dict__.copy()
        d["verbs"] = [dict(v) for v in self.verbs]
        d["journal_append"] = [dict(j) for j in self.journal_append]
        return d


def parse_action_output(obj):
    _require_schema(obj, SCHEMA_ACTION)
    verbs = obj.get("verbs", [])
    if not isinstance(verbs, list) or any(not isinstance(v, dict) for v in verbs):
        raise ContractError("action.verbs must be a list of objects")
    appends = obj.get("journal_append", [])
    if not isinstance(appends, list) or any(not isinstance(j, dict) for j in appends):
        raise ContractError("action.journal_append must be a list of objects")
    proposal = obj.get("memory_proposal")
    if proposal is not None:
        if not isinstance(proposal, dict):
            raise ContractError("action.memory_proposal must be an object or null")
        region = proposal.get("region")
        if region not in MEMORY_REGIONS:
            raise ContractError(f"memory_proposal.region {region!r} not in {MEMORY_REGIONS}")
        if region == "identity_core":
            raise ContractError("a waking seat can never target identity_core")
    return ActionOutput(
        tick_id=_require(obj, "tick_id", int, "action"),
        lease_id=_require(obj, "lease_id", str, "action"),
        epoch=_require(obj, "epoch", int, "action"),
        action_id=_require(obj, "action_id", str, "action"),
        verbs=tuple(verbs),
        journal_append=tuple(appends),
        memory_proposal=proposal,
    )


@dataclass(frozen=True)
class HandoffRecord:
    """One completed seat handoff: an auditable state transition, not a prompt."""
    from_seat: str
    to_seat: str
    old_lease: str
    new_lease: str
    epoch: int
    journal_snapshot_hash: str
    drained: bool
    body_terminal: str      # "limp" | "neutral"
    granted_capabilities: tuple
    human_ack: dict | None  # {"by": ..., "at": ...}; required for any grant beyond OBSERVE_ONLY
    schema: str = SCHEMA_HANDOFF

    def to_dict(self):
        d = self.__dict__.copy()
        d["granted_capabilities"] = list(self.granted_capabilities)
        return d


def parse_handoff(obj):
    _require_schema(obj, SCHEMA_HANDOFF)
    caps = _require(obj, "granted_capabilities", list, "handoff")
    bad = [c for c in caps if c not in CAPABILITIES]
    if bad:
        raise ContractError(f"handoff.granted_capabilities has unknown entries {bad}")
    terminal = _require(obj, "body_terminal", str, "handoff")
    if terminal not in ("limp", "neutral"):
        raise ContractError(f"handoff.body_terminal {terminal!r} must be 'limp' or 'neutral'")
    ack = obj.get("human_ack")
    if ack is not None and not isinstance(ack, dict):
        raise ContractError("handoff.human_ack must be an object or null")
    if any(c != "OBSERVE_ONLY" for c in caps) and not ack:
        raise ContractError("capabilities beyond OBSERVE_ONLY require human_ack")
    drained = obj.get("drained")
    if not isinstance(drained, bool):
        raise ContractError("handoff.drained must be a boolean")
    return HandoffRecord(
        from_seat=_require(obj, "from_seat", str, "handoff"),
        to_seat=_require(obj, "to_seat", str, "handoff"),
        old_lease=_require(obj, "old_lease", str, "handoff"),
        new_lease=_require(obj, "new_lease", str, "handoff"),
        epoch=_require(obj, "epoch", int, "handoff"),
        journal_snapshot_hash=_require(obj, "journal_snapshot_hash", str, "handoff"),
        drained=drained,
        body_terminal=terminal,
        granted_capabilities=tuple(caps),
        human_ack=ack,
    )


@dataclass(frozen=True)
class DreamInput:
    """The frozen evidence packet a dream round consolidates (logical #102)."""
    creature_id: str
    evidence_hash: str
    diary: tuple
    working_memory: dict
    staged_proposals: tuple
    reason: str
    schema: str = SCHEMA_DREAM

    def to_dict(self):
        d = self.__dict__.copy()
        d["diary"] = list(self.diary)
        d["staged_proposals"] = [dict(p) for p in self.staged_proposals]
        return d


def parse_dream_input(obj):
    _require_schema(obj, SCHEMA_DREAM)
    diary = _require(obj, "diary", list, "dream")
    proposals = obj.get("staged_proposals", [])
    if not isinstance(proposals, list) or any(not isinstance(p, dict) for p in proposals):
        raise ContractError("dream.staged_proposals must be a list of objects")
    return DreamInput(
        creature_id=_require(obj, "creature_id", str, "dream"),
        evidence_hash=_require(obj, "evidence_hash", str, "dream"),
        diary=tuple(diary),
        working_memory=_require(obj, "working_memory", dict, "dream"),
        staged_proposals=tuple(proposals),
        reason=_require(obj, "reason", str, "dream"),
    )


@dataclass(frozen=True)
class DreamPass:
    """One seat's blind first pass over a frozen dream packet.

    Concerns are the deterministic hook for dissent discipline: every seat
    that files a non-empty concern must see it explicitly disposed in the
    final commit (accepted / parked-with-clock / rejected-with-reason).
    """
    seat: str
    evidence_hash: str
    proposal: dict
    concerns: tuple
    schema: str = SCHEMA_DREAM_PASS

    def to_dict(self):
        d = self.__dict__.copy()
        d["concerns"] = list(self.concerns)
        return d


def parse_dream_pass(obj):
    _require_schema(obj, SCHEMA_DREAM_PASS)
    concerns = obj.get("concerns", [])
    if not isinstance(concerns, list) or any(not isinstance(c, str) or not c.strip() for c in concerns):
        raise ContractError("dream_pass.concerns must be a list of non-empty strings")
    return DreamPass(
        seat=_require(obj, "seat", str, "dream_pass"),
        evidence_hash=_require(obj, "evidence_hash", str, "dream_pass"),
        proposal=_require(obj, "proposal", dict, "dream_pass"),
        concerns=tuple(concerns),
    )


@dataclass(frozen=True)
class DreamCommit:
    """What a dream round proposes back. Deterministic clamps run after parse."""
    evidence_hash: str
    commit_status: str
    mutations: tuple
    dissents: tuple
    schema: str = SCHEMA_DREAM_COMMIT

    def to_dict(self):
        d = self.__dict__.copy()
        d["mutations"] = [dict(m) for m in self.mutations]
        d["dissents"] = [dict(x) for x in self.dissents]
        return d


def parse_dream_commit(obj):
    _require_schema(obj, SCHEMA_DREAM_COMMIT)
    status = _require(obj, "commit_status", str, "dream_commit")
    if status not in DREAM_COMMIT_STATUSES:
        raise ContractError(f"commit_status {status!r} not in {DREAM_COMMIT_STATUSES}")
    mutations = obj.get("mutations", [])
    if not isinstance(mutations, list):
        raise ContractError("dream_commit.mutations must be a list")
    for m in mutations:
        if not isinstance(m, dict):
            raise ContractError("dream_commit.mutations items must be objects")
        if m.get("region") not in MEMORY_REGIONS:
            raise ContractError(f"mutation.region {m.get('region')!r} not in {MEMORY_REGIONS}")
        for req in ("op", "expected_version", "proposer", "risk_class", "approval_class"):
            if req not in m:
                raise ContractError(f"mutation missing {req!r}")
        refs = m.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise ContractError("every mutation needs non-empty evidence_refs")
    dissents = obj.get("dissents", [])
    if not isinstance(dissents, list) or any(not isinstance(x, dict) for x in dissents):
        raise ContractError("dream_commit.dissents must be a list of objects")
    for x in dissents:
        if x.get("disposition") == "parked":
            if not x.get("review_by"):
                raise ContractError("a parked dissent needs a review_by clock")
            if x.get("on_expiry") != "surface_for_disposition":
                raise ContractError("parked dissents must surface_for_disposition on expiry")
    return DreamCommit(
        evidence_hash=_require(obj, "evidence_hash", str, "dream_commit"),
        commit_status=status,
        mutations=tuple(mutations),
        dissents=tuple(dissents),
    )
