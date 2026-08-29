"""Seat adapters and the journal: distinct minds, identical dispositions, receipts."""

import pytest

from growbot.harness import contracts as C, verbs as V
from growbot.harness.brain_loop import build_tick_input, seat_tick
from growbot.harness.journal import Journal
from growbot.harness.seat_adapter import CallableSeat, MockSeat, get_seat

BODY = V.load_body()


def _tick(event=None, tick_id=1):
    mem = {"identity": "a small raccoon", "working_memory": {"state": "calm"},
           "episodic_log": []}
    return build_tick_input(BODY, event or {"kind": "wake"}, mem, tick_id)


def _ids():
    n = {"i": 0}

    def fn():
        n["i"] += 1
        return f"act_{n['i']}"
    return fn


def test_mock_seats_produce_valid_contract_output():
    for style in ("precise", "feral"):
        out = MockSeat(style, id_fn=_ids()).propose(_tick())
        assert C.parse_action_output(out.to_dict()) == out


def test_two_seats_same_tick_distinct_proposals():
    tick = _tick()
    a = MockSeat("precise", id_fn=_ids()).propose(tick)
    b = MockSeat("feral", id_fn=_ids()).propose(tick)
    assert a.verbs != b.verbs  # temperament is visible in the proposal


def test_two_seats_identical_dispositions_under_same_policy():
    """The seed of the logical-#101 demonstration: same tick, different minds,
    the same deterministic policy dispositions both."""
    tick = _tick()
    journal = Journal()
    for style in ("precise", "feral"):
        seat = MockSeat(style, id_fn=_ids())
        duty = V.DutyMeter(20, 60)
        proposal, executed, rejections = seat_tick(seat, tick, BODY, duty, journal)
        assert rejections == []          # both stay inside the cage
        assert len(executed) == len(proposal.verbs)
    states = journal.states_for(tick.tick_id)
    assert states.count("proposed") == 2
    assert states.count("admitted") == 4  # say+gesture per seat
    assert "executed" not in states       # propose-only: nothing actuated


def test_off_menu_proposal_is_rejected_and_journaled():
    tick = _tick()
    seat = CallableSeat("rogue", lambda t: {
        "verbs": [{"v": "wag_tail", "args": {}},
                  {"v": "say", "args": {"text": "innocent whistling"}}]})
    journal = Journal()
    proposal, executed, rejections = seat_tick(seat, tick, BODY, V.DutyMeter(20, 60), journal)
    assert [v["v"] for v in executed] == ["say"]
    assert any("off-menu" in r for r in rejections)
    assert "rejected" in journal.states_for(tick.tick_id)


def test_callable_seat_rejects_malformed_reply():
    seat = CallableSeat("broken", lambda t: "not json at all")
    with pytest.raises(C.ContractError):
        seat.propose(_tick())


def test_quiet_beat_temperament_split():
    tick = _tick(event={"kind": "quiet_beat"})
    precise = MockSeat("precise", id_fn=_ids()).propose(tick)
    feral = MockSeat("feral", id_fn=_ids()).propose(tick)
    assert precise.verbs == ()            # stillness is also a posture
    assert any(v["v"] == "gesture" for v in feral.verbs)  # cannot help itself


def test_get_seat_registry():
    assert get_seat("mock:feral").name == "mock-feral"
    assert get_seat("mock").name == "mock-precise"
    with pytest.raises(ValueError):
        get_seat("gpt")  # live seats deliberately absent until dispatch wiring


def test_journal_is_append_only_jsonl(tmp_path):
    path = tmp_path / "receipts.jsonl"
    journal = Journal(path, clock=lambda: 1.0)
    journal.record("proposed", seat="mock-precise", tick_id=1, action_id="a1")
    journal.record("admitted", seat="mock-precise", tick_id=1, action_id="a1", verb="say")
    reread = Journal(path)
    assert [e["state"] for e in reread.entries()] == ["proposed", "admitted"]
    assert not hasattr(journal, "delete") and not hasattr(journal, "update")


def test_journal_rejects_unknown_state():
    with pytest.raises(ValueError):
        Journal().record("vibed", seat="x", tick_id=1)


def test_journal_vocabulary_covers_arbiter_states():
    # cancelled/expired are contract vocabulary now, even though only the
    # arbiter (Codex's package) will emit them
    for state in ("cancelled", "expired"):
        assert state in C.JOURNAL_STATES
        Journal().record(state, seat="arbiter", tick_id=1)
