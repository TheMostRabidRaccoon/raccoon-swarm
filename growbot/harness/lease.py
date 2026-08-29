"""Host-owned waking-seat leases and capability transitions.

The model sees lease_id and epoch in its TickInput, but it never receives the
opaque LeaseProof required by the arbiter.  A provider (or fallback) therefore
cannot establish seat presence merely by repeating serialized lease fields.

Logical #101 only: no body client and no actuation imports.
"""

from __future__ import annotations

from dataclasses import dataclass
import secrets
import time

if __package__ in (None, ""):
    import contracts  # pragma: no cover
else:
    from . import contracts


def _monotonic_ms():
    return int(time.monotonic() * 1000)


class LeaseError(ValueError):
    """A requested lease transition violated the deterministic policy."""


class LeaseProof:
    """Opaque, host-local proof of lease possession; never serialize this."""

    __slots__ = ("_token",)

    def __init__(self, token):
        self._token = token

    def __repr__(self):  # keep logs from accidentally disclosing the proof
        return "LeaseProof(<host-only>)"


@dataclass(frozen=True)
class LeaseSnapshot:
    seat: str
    lease_id: str
    epoch: int
    state: str
    capabilities: tuple
    issued_monotonic_ms: int
    expires_monotonic_ms: int
    fault_reason: str | None = None


@dataclass(frozen=True)
class LeaseGrant:
    lease: LeaseSnapshot
    proof: LeaseProof


@dataclass(frozen=True)
class LeaseCheck:
    ok: bool
    reason: str = ""


class LeaseManager:
    """One creature, one revocable waking lease, monotonically increasing epochs."""

    def __init__(self, *, clock_ms=_monotonic_ms, lease_id_fn=None, proof_token_fn=None):
        self._clock_ms = clock_ms
        self._lease_id_fn = lease_id_fn or (lambda epoch: f"lease_{epoch}_{secrets.token_hex(4)}")
        self._proof_token_fn = proof_token_fn or (lambda: secrets.token_urlsafe(24))
        self._epoch = 0
        self._current = None
        self._proof_token = None
        self._capability_expiry = {}

    @property
    def epoch(self):
        return self._epoch

    def issue(self, seat, *, ttl_ms=30_000):
        if not isinstance(seat, str) or not seat.strip():
            raise LeaseError("seat must be a non-empty string")
        if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or ttl_ms <= 0:
            raise LeaseError("ttl_ms must be a positive integer")
        if self._current is not None and self._current["state"] not in ("REVOKED", "FAULTED"):
            raise LeaseError("the current lease must be revoked or faulted before issuing another")

        now = self._clock_ms()
        self._epoch += 1
        token = self._proof_token_fn()
        self._proof_token = token
        self._capability_expiry = {"OBSERVE_ONLY": now + ttl_ms}
        self._current = {
            "seat": seat,
            "lease_id": self._lease_id_fn(self._epoch),
            "epoch": self._epoch,
            "state": "OBSERVE_ONLY",
            "issued_monotonic_ms": now,
            "expires_monotonic_ms": now + ttl_ms,
            "fault_reason": None,
        }
        return LeaseGrant(self.snapshot(), LeaseProof(token))

    def snapshot(self):
        if self._current is None:
            return None
        self._refresh()
        return LeaseSnapshot(
            seat=self._current["seat"], lease_id=self._current["lease_id"],
            epoch=self._current["epoch"], state=self._current["state"],
            capabilities=self._active_capabilities(),
            issued_monotonic_ms=self._current["issued_monotonic_ms"],
            expires_monotonic_ms=self._current["expires_monotonic_ms"],
            fault_reason=self._current["fault_reason"],
        )

    def grant(self, capability, proof, *, ttl_ms, human_ack, prerequisites_met):
        """Promote one separately expiring capability.

        Threshold details stay policy parameters supplied by the caller.  This
        module enforces that both the deterministic prerequisite and explicit
        human acknowledgement exist; it does not hardcode an N-clean-ticks rule.
        """
        if capability not in ("SPEECH_GESTURE", "LOCOMOTION_AUTHORIZED"):
            raise LeaseError("only SPEECH_GESTURE or LOCOMOTION_AUTHORIZED may be granted")
        check = self.validate(proof, seat=self._seat(), lease_id=self._lease_id(), epoch=self._epoch)
        if not check.ok:
            raise LeaseError(check.reason)
        if not prerequisites_met:
            raise LeaseError("deterministic promotion prerequisites are not met")
        if not isinstance(human_ack, dict) or not human_ack.get("by") or not human_ack.get("at"):
            raise LeaseError("promotion requires explicit human_ack with by and at")
        if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or ttl_ms <= 0:
            raise LeaseError("ttl_ms must be a positive integer")
        if capability == "LOCOMOTION_AUTHORIZED" and "SPEECH_GESTURE" not in self._active_capabilities():
            raise LeaseError("locomotion requires an active SPEECH_GESTURE capability")

        now = self._clock_ms()
        expiry_caps = [now + ttl_ms, self._current["expires_monotonic_ms"]]
        if capability == "LOCOMOTION_AUTHORIZED":
            # A higher rung may never outlive the rung beneath it.
            expiry_caps.append(self._capability_expiry["SPEECH_GESTURE"])
        self._capability_expiry[capability] = min(expiry_caps)
        self._refresh()
        return self.snapshot()

    def begin_quiesce(self, proof):
        self._refresh()
        check = self._check_proof(proof)
        if not check.ok:
            raise LeaseError(check.reason)
        if self._current["state"] in ("REVOKED", "FAULTED"):
            raise LeaseError(f"cannot quiesce a {self._current['state']} lease")
        self._current["state"] = "QUIESCING"
        self._capability_expiry = {}
        return self.snapshot()

    def complete_revoke(self, proof, *, drained, body_terminal):
        check = self._check_proof(proof)
        if not check.ok:
            raise LeaseError(check.reason)
        if self._current["state"] != "QUIESCING":
            raise LeaseError("lease must be QUIESCING before revocation completes")
        if drained is not True:
            raise LeaseError("revocation requires drained actions")
        if body_terminal not in ("limp", "neutral"):
            raise LeaseError("body_terminal must be limp or neutral")
        self._current["state"] = "REVOKED"
        self._proof_token = None
        return self.snapshot()

    def fault_current(self, *, expected_seat, reason):
        """Host records provider absence; no replacement lease is synthesized."""
        if self._current is None or self._current["seat"] != expected_seat:
            raise LeaseError("provider failure does not match the current seat")
        if self._current["state"] in ("REVOKED", "FAULTED"):
            return self.snapshot()
        self._current["state"] = "FAULTED"
        self._current["fault_reason"] = str(reason)
        self._capability_expiry = {}
        self._proof_token = None
        return self.snapshot()

    def validate(self, proof, *, seat, lease_id, epoch, required_capabilities=()):
        if self._current is None:
            return LeaseCheck(False, "no waking lease exists")
        now = self._clock_ms()
        if now >= self._current["expires_monotonic_ms"]:
            self._expire()
            return LeaseCheck(False, "lease expired")
        proof_check = self._check_proof(proof)
        if not proof_check.ok:
            return proof_check
        if seat != self._current["seat"]:
            return LeaseCheck(False, "claimed seat is not the leased waking seat")
        if lease_id != self._current["lease_id"]:
            return LeaseCheck(False, "lease_id does not match the current lease")
        if epoch != self._current["epoch"]:
            return LeaseCheck(False, "epoch does not match the current lease")
        if self._current["state"] in ("REVOKED", "QUIESCING", "FAULTED"):
            return LeaseCheck(False, f"lease state {self._current['state']} cannot admit actions")
        self._refresh()
        active = set(self._active_capabilities())
        missing = [c for c in required_capabilities if c not in active]
        if missing:
            return LeaseCheck(False, f"missing active capabilities: {', '.join(missing)}")
        return LeaseCheck(True)

    def _refresh(self):
        if self._current is None or self._current["state"] in ("REVOKED", "QUIESCING", "FAULTED"):
            return
        now = self._clock_ms()
        if now >= self._current["expires_monotonic_ms"]:
            self._expire()
            return
        for cap, expiry in list(self._capability_expiry.items()):
            if now >= expiry:
                del self._capability_expiry[cap]
        active = set(self._capability_expiry)
        if "LOCOMOTION_AUTHORIZED" in active:
            self._current["state"] = "LOCOMOTION_AUTHORIZED"
        elif "SPEECH_GESTURE" in active:
            self._current["state"] = "SPEECH_GESTURE"
        else:
            self._current["state"] = "OBSERVE_ONLY"

    def _expire(self):
        self._current["state"] = "REVOKED"
        self._capability_expiry = {}
        self._proof_token = None

    def _active_capabilities(self):
        if self._current is None or self._current["state"] in ("REVOKED", "QUIESCING", "FAULTED"):
            return ()
        order = contracts.CAPABILITIES
        return tuple(cap for cap in order if cap in self._capability_expiry)

    def _check_proof(self, proof):
        if not isinstance(proof, LeaseProof) or self._proof_token is None:
            return LeaseCheck(False, "valid host-local lease proof required")
        if not secrets.compare_digest(proof._token, self._proof_token):
            return LeaseCheck(False, "valid host-local lease proof required")
        return LeaseCheck(True)

    def _seat(self):
        return self._current["seat"] if self._current else ""

    def _lease_id(self):
        return self._current["lease_id"] if self._current else ""
