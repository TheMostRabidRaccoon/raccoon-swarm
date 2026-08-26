"""Deterministic admission, idempotency, and absence handling.

The arbiter consumes parsed contracts.  It owns freshness, epoch, opaque lease
proof, capability, memory-envelope, duplicate-action, and cancellation policy.
It deliberately imports no physical body implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import time

if __package__ in (None, ""):
    import contracts, verbs  # pragma: no cover
else:
    from . import contracts, verbs


def _monotonic_ms():
    return int(time.monotonic() * 1000)


@dataclass(frozen=True)
class Disposition:
    action_id: str
    tick_id: int
    lease_id: str
    epoch: int
    seat: str
    state: str
    admitted_verbs: tuple = ()
    rejected_reasons: tuple = ()
    reason: str = ""
    duplicate: bool = False


@dataclass(frozen=True)
class CancellationDisposition:
    cancellation_id: str
    target_action_id: str
    state: str
    reason: str = ""
    duplicate: bool = False


class Arbiter:
    """Dispose model proposals exactly once under the current waking lease."""

    def __init__(self, lease_manager, body, journal, *, duty=None, executor=None,
                 clock_ms=_monotonic_ms):
        self.leases = lease_manager
        self.body = body
        self.journal = journal
        self.duty = duty or verbs.DutyMeter(
            body["limits"].get("duty_motion_s", 20),
            body["limits"].get("duty_window_s", 60))
        self.executor = executor
        self._clock_ms = clock_ms
        self._actions = {}
        self._cancellations = {}
        self._restore_ledgers()

    def dispose(self, tick, action, *, seat, proof):
        """Return the deterministic disposition; duplicates never execute twice."""
        if not isinstance(tick, contracts.TickInput):
            tick = contracts.parse_tick_input(tick)
        if not isinstance(action, contracts.ActionOutput):
            action = contracts.parse_action_output(action)

        prior = self._actions.get(action.action_id)
        if prior is not None:
            return replace(prior, duplicate=True)

        invalid = self._validate_envelope(tick, action, seat=seat, proof=proof)
        receipt_seat = seat if invalid is None else "unverified"
        self.journal.record(
            "proposed", seat=receipt_seat, tick_id=action.tick_id,
            action_id=action.action_id,
            extra={"lease_id": action.lease_id, "epoch": action.epoch,
                   "verbs": [v.get("v") for v in action.verbs],
                   **({"claimed_seat": seat} if invalid else {})})

        if invalid:
            state, reason = invalid
            return self._terminal(action, seat, state, reason,
                                  journal_seat="arbiter",
                                  extra={"claimed_seat": seat})

        memory_error = self._validate_memory(action, seat)
        if memory_error:
            return self._terminal(action, seat, "rejected", memory_error)

        permitted_calls, capability_rejections = self._capability_filter(action.verbs)
        admitted, verb_rejections = verbs.filter_tick(permitted_calls, self.body, self.duty)
        rejections = capability_rejections + verb_rejections
        for reason in rejections:
            self.journal.record("rejected", seat=seat, tick_id=action.tick_id,
                                action_id=action.action_id, reason=reason)

        for verb in admitted:
            self.journal.record("admitted", seat=seat, tick_id=action.tick_id,
                                action_id=action.action_id, verb=verb["v"])

        if not admitted and rejections:
            result = Disposition(
                action.action_id, action.tick_id, action.lease_id, action.epoch,
                seat, "rejected", rejected_reasons=tuple(rejections),
                reason="no proposed verb was admissible")
            self._actions[action.action_id] = result
            return result

        # Silence is an admissible OBSERVE_ONLY outcome and still gets a receipt.
        if not admitted:
            self.journal.record("admitted", seat=seat, tick_id=action.tick_id,
                                action_id=action.action_id, reason="admitted silence")

        state = "admitted"
        if self.executor is not None:
            try:
                for verb in admitted:
                    self.executor.execute(verb)
                    self.journal.record("executed", seat=seat, tick_id=action.tick_id,
                                        action_id=action.action_id, verb=verb["v"])
                state = "executed"
            except Exception as exc:
                reason = f"executor failure: {type(exc).__name__}: {exc}"
                self.journal.record("cancelled", seat=seat, tick_id=action.tick_id,
                                    action_id=action.action_id, reason=reason)
                self.leases.fault_current(expected_seat=seat, reason=reason)
                state = "cancelled"

        result = Disposition(
            action.action_id, action.tick_id, action.lease_id, action.epoch,
            seat, state, admitted_verbs=tuple(admitted),
            rejected_reasons=tuple(rejections))
        self._actions[action.action_id] = result
        return result

    def cancel(self, cancellation_id, target_action_id, *, seat):
        """Idempotently cancel an admitted, not-yet-executed action."""
        prior = self._cancellations.get(cancellation_id)
        if prior is not None:
            return replace(prior, duplicate=True)
        target = self._actions.get(target_action_id)
        if target is None:
            result = CancellationDisposition(cancellation_id, target_action_id,
                                             "rejected", "unknown target action")
        elif target.seat != seat:
            result = CancellationDisposition(cancellation_id, target_action_id,
                                             "rejected", "seat does not own target action")
        elif target.state != "admitted":
            result = CancellationDisposition(cancellation_id, target_action_id,
                                             "rejected", f"target already {target.state}")
        else:
            cancelled = replace(target, state="cancelled", reason="cancelled by host")
            self._actions[target_action_id] = cancelled
            self.journal.record("cancelled", seat=seat, tick_id=target.tick_id,
                                action_id=target_action_id,
                                reason="cancelled by host",
                                extra={"cancellation_id": cancellation_id})
            result = CancellationDisposition(cancellation_id, target_action_id, "cancelled")
        self._cancellations[cancellation_id] = result
        return result

    def provider_failed(self, seat, reason):
        """Fault exactly the expected seat, cancel its open actions, record absence."""
        current = self.leases.snapshot()
        if current is None or current.seat != seat:
            raise ValueError("provider failure does not match the leased waking seat")
        for action_id, disposition in list(self._actions.items()):
            if disposition.seat == seat and disposition.state == "admitted":
                self._actions[action_id] = replace(
                    disposition, state="cancelled", reason="provider absent")
                self.journal.record("cancelled", seat=seat,
                                    tick_id=disposition.tick_id,
                                    action_id=action_id, reason="provider absent")
        faulted = self.leases.fault_current(expected_seat=seat, reason=reason)
        self.journal.record(
            "cancelled", seat=seat, tick_id=-1, reason="provider absent",
            extra={"presence": "absent", "provider_error": str(reason),
                   "lease_id": faulted.lease_id, "epoch": faulted.epoch})
        return faulted

    def disposition_for(self, action_id):
        return self._actions.get(action_id)

    def _validate_envelope(self, tick, action, *, seat, proof):
        if self._clock_ms() >= tick.deadline_monotonic_ms:
            return "expired", "tick deadline expired"
        if action.tick_id != tick.tick_id:
            return "rejected", "action tick_id does not match tick"
        if action.lease_id != tick.lease_id or action.epoch != tick.epoch:
            return "rejected", "action lease fields do not match tick"
        check = self.leases.validate(
            proof, seat=seat, lease_id=action.lease_id, epoch=action.epoch)
        if not check.ok:
            state = "expired" if "expired" in check.reason else "rejected"
            return state, check.reason
        if tuple(tick.capabilities) != self.leases.snapshot().capabilities:
            return "rejected", "tick capabilities do not match the live lease"
        return None

    def _validate_memory(self, action, seat):
        proposal = action.memory_proposal
        if proposal is not None:
            if proposal.get("region") != "seat_journal":
                return "waking actions may propose only seat_journal mutations"
            if proposal.get("op") != "append":
                return "waking seat_journal mutations must be append-only"
            if proposal.get("seat") not in (None, seat):
                return "seat_journal mutation cannot be attributed to another seat"
        for entry in action.journal_append:
            if entry.get("seat") not in (None, seat):
                return "journal append cannot fabricate another seat's presence"
        return None

    def _capability_filter(self, calls):
        active = set((self.leases.snapshot() or ()).capabilities)
        permitted, rejected = [], []
        for call in calls:
            name = call.get("v")
            required = None
            if name in ("say", "gesture", "rest"):
                required = "SPEECH_GESTURE"
            elif name == "walk":
                required = "LOCOMOTION_AUTHORIZED"
            if required and required not in active:
                rejected.append(f"{name}: missing active capability {required}")
            else:
                permitted.append(call)
        return permitted, rejected

    def _terminal(self, action, seat, state, reason, *, journal_seat=None, extra=None):
        self.journal.record(state, seat=journal_seat or seat, tick_id=action.tick_id,
                            action_id=action.action_id, reason=reason, extra=extra)
        result = Disposition(
            action.action_id, action.tick_id, action.lease_id, action.epoch,
            seat, state, reason=reason, rejected_reasons=(reason,))
        self._actions[action.action_id] = result
        return result

    def _restore_ledgers(self):
        """Recover duplicate suppression from the append-only journal.

        A host restart must not turn a retried action into a fresh action.  The
        journal intentionally reconstructs only the safety-relevant prior
        disposition; verb payloads are not replayed from receipts.
        """
        for entry in self.journal.entries():
            action_id = entry.get("action_id")
            if action_id:
                state = entry.get("state")
                if state in contracts.JOURNAL_STATES:
                    prior = self._actions.get(action_id)
                    self._actions[action_id] = Disposition(
                        action_id=action_id,
                        tick_id=entry.get("tick_id", prior.tick_id if prior else -1),
                        lease_id=entry.get("lease_id", prior.lease_id if prior else ""),
                        epoch=entry.get("epoch", prior.epoch if prior else -1),
                        seat=entry.get("seat", prior.seat if prior else "unknown"),
                        state=state,
                        reason=entry.get("reason", prior.reason if prior else ""),
                    )
            cancellation_id = entry.get("cancellation_id")
            if cancellation_id and action_id:
                self._cancellations[cancellation_id] = CancellationDisposition(
                    cancellation_id, action_id, "cancelled")
