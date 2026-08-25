"""The GrowBot verb contract: off-menu rejection, clamping, budgets.

The rejections working IS the health signal of the design — a model (or a
whole Council) gets exactly the menu and nothing else.
"""

from growbot.harness import verbs as V

BODY = V.load_body()


def _gesture(steps):
    return {"v": "gesture", "args": {"steps": steps}}


def test_off_menu_verb_rejected():
    r = V.validate_verb({"v": "wag_tail", "args": {}}, BODY)
    assert not r["ok"]
    assert "off-menu" in r["why"]


def test_malformed_call_rejected():
    assert not V.validate_verb(None, BODY)["ok"]
    assert not V.validate_verb({"args": {}}, BODY)["ok"]


def test_gesture_angles_clamped_not_crashed():
    r = V.validate_verb(_gesture([{"l": 999, "r": -40, "ms": 400}]), BODY)
    assert r["ok"]
    step = r["args"]["steps"][0]
    assert step["l"] == 130  # hallucinated 999 means "far", clamped to the band
    assert step["r"] == 50
    assert step["ms"] == 400


def test_gesture_omitted_leg_holds():
    r = V.validate_verb(_gesture([{"l": 70, "ms": 300}]), BODY)
    assert r["ok"]
    assert "r" not in r["args"]["steps"][0]


def test_gesture_missing_ms_rejected():
    r = V.validate_verb(_gesture([{"l": 70, "r": 110}]), BODY)
    assert not r["ok"]


def test_gesture_total_ms_capped():
    r = V.validate_verb(_gesture([{"l": 90, "r": 90, "ms": 2000}] * 3), BODY)
    assert r["ok"]
    total = sum(s["ms"] for s in r["args"]["steps"])
    assert total <= 3000


def test_walk_secs_clamped():
    r = V.validate_verb({"v": "walk", "args": {"secs": 500}}, BODY)
    assert r["ok"]
    assert r["args"]["secs"] == 8


def test_say_truncated_to_word_cap():
    r = V.validate_verb({"v": "say", "args": {"text": "word " * 30}}, BODY)
    assert r["ok"]
    assert len(r["args"]["text"].split()) == 18


def test_one_motion_verb_per_tick():
    calls = [_gesture([{"l": 90, "r": 90, "ms": 200}]),
             {"v": "walk", "args": {"secs": 1}},
             {"v": "say", "args": {"text": "still allowed"}}]
    executed, rejections = V.filter_tick(calls, BODY)
    assert [v["v"] for v in executed] == ["gesture", "say"]
    assert any("motion budget" in why for why in rejections)


def test_duty_meter_refuses_past_cap():
    t = {"now": 0.0}
    duty = V.DutyMeter(motion_s=5, window_s=60, clock=lambda: t["now"])
    assert duty.allow(4)
    assert not duty.allow(2)  # 4 + 2 > 5
    t["now"] = 61  # the window rolls; the spend expires
    assert duty.allow(5)


def test_filter_tick_enforces_duty_window():
    duty = V.DutyMeter(motion_s=1, window_s=60)
    calls = [_gesture([{"l": 90, "r": 90, "ms": 2000}])]  # 2 s > 1 s budget
    executed, rejections = V.filter_tick(calls, BODY, duty)
    assert executed == []
    assert any("duty window" in why for why in rejections)
