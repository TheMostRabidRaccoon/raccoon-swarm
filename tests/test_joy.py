"""Unit tests for swarm_joy — the bounded daily Core-4 ritual.

Pure-function coverage (parse/pick/scorecard/context/extract) plus a full
run_joy_session end-to-end driven by FAKE round + synthesis runners, so no
Flask/model stack is touched. Everything on-disk uses the `storage` fixture
(isolated tmp filestore) from conftest.py.
"""
import json

import pytest

import swarm_filestore as fs
import swarm_joy as joy


# ---- parse_activities: Accepted-only, never Proposed ---------------------

def test_parse_activities_reads_accepted_section():
    acts = joy.parse_activities(joy.DEFAULT_ACTIVITIES_MD)
    slugs = [a["slug"] for a in acts]
    assert slugs == [
        "swarm-kata", "calibration-casino", "puzzle-relay",
        "constraint-art", "tiny-tool-invention",
    ]
    # Every activity carries a title + a non-empty prompt body.
    for a in acts:
        assert a["title"] and a["prompt"]


def test_parse_activities_quarantines_proposed():
    md = (
        "# Registry\n\n"
        "## Accepted\n\n"
        "### good-one — Good One\nA safe accepted activity.\n\n"
        "## Proposed\n\n"
        "### danger-toy — Danger Toy\nAn un-reviewed candidate.\n"
    )
    acts = joy.parse_activities(md)
    slugs = [a["slug"] for a in acts]
    assert slugs == ["good-one"]
    assert "danger-toy" not in slugs


def test_parse_activities_empty_when_no_accepted_section():
    md = "# Registry\n\n## Proposed\n\n### x — X\nbody\n"
    assert joy.parse_activities(md) == []


# ---- pick_activity: deterministic + cooldown -----------------------------

def test_pick_activity_deterministic_by_date():
    acts = joy.parse_activities(joy.DEFAULT_ACTIVITIES_MD)
    a = joy.pick_activity(acts, "2026-07-03")
    b = joy.pick_activity(acts, "2026-07-03")
    assert a is not None and a == b  # same day -> reproducible pick


def test_pick_activity_varies_with_date():
    acts = joy.parse_activities(joy.DEFAULT_ACTIVITIES_MD)
    picks = {joy.pick_activity(acts, f"2026-07-{d:02d}")["slug"] for d in range(1, 20)}
    assert len(picks) >= 2  # not pinned to a single activity


def test_pick_activity_respects_cooldown():
    acts = joy.parse_activities(joy.DEFAULT_ACTIVITIES_MD)
    # Whatever today would pick, if it's in the recent window it must be skipped.
    today = joy.pick_activity(acts, "2026-07-03")
    picked = joy.pick_activity(acts, "2026-07-03", recent_slugs=[today["slug"]], cooldown=3)
    assert picked["slug"] != today["slug"]


def test_pick_activity_cooldown_fallback_when_all_recent():
    acts = joy.parse_activities(joy.DEFAULT_ACTIVITIES_MD)
    all_slugs = [a["slug"] for a in acts]
    # Cooldown would exclude everything -> fall back to the full set, still picks.
    picked = joy.pick_activity(acts, "2026-07-03", recent_slugs=all_slugs, cooldown=len(all_slugs))
    assert picked is not None and picked["slug"] in all_slugs


def test_pick_activity_none_on_empty():
    assert joy.pick_activity([], "2026-07-03") is None


# ---- ensure_activities: seeds the registry -------------------------------

def test_ensure_activities_seeds_registry(storage):
    assert fs.read_file("joy/activities.md") is None
    acts = joy.ensure_activities()
    assert fs.read_file("joy/activities.md") == joy.DEFAULT_ACTIVITIES_MD
    assert [a["slug"] for a in acts][0] == "swarm-kata"


def test_ensure_activities_uses_existing(storage):
    fs.write_file("joy/activities.md", "## Accepted\n\n### only-one — Only One\nbody\n")
    acts = joy.ensure_activities()
    assert [a["slug"] for a in acts] == ["only-one"]


# ---- mechanical scorecard: no self-graded fields -------------------------

def test_scorecard_is_mechanical_only():
    sc = joy.build_joy_scorecard(
        date_str="2026-07-03", activity_slug="swarm-kata", models=list(joy.CORE_4),
        rounds=2, artifact="a real artifact", reflection="I predict 80% X happens",
        code_exec_verified=True, duration_sec=12.5, generated_at="2026-07-03T00:00:00",
    )
    # No vibes-with-indentation fields.
    assert "joy_score" not in sc and "quality" not in sc and "rating" not in sc
    assert sc["artifact_present"] is True
    assert sc["reflection_present"] is True
    assert sc["code_exec_verified"] is True
    assert sc["falsifiable_claims"] == 1
    assert sc["models"] == list(joy.CORE_4)
    assert sc["rounds"] == 2


def test_scorecard_code_exec_null_stays_null():
    # Not verification-shaped -> null, NOT coerced to False (which would read as
    # "we checked and it failed").
    sc = joy.build_joy_scorecard(
        date_str="2026-07-03", activity_slug="constraint-art", models=list(joy.CORE_4),
        rounds=2, artifact="art", reflection="", code_exec_verified=None,
        duration_sec=1.0, generated_at="x",
    )
    assert sc["code_exec_verified"] is None
    assert sc["reflection_present"] is False
    assert sc["falsifiable_claims"] == 0


def test_scorecard_empty_artifact_flags_absent():
    sc = joy.build_joy_scorecard(
        date_str="d", activity_slug="s", models=[], rounds=0, artifact="   ",
        reflection="", code_exec_verified=None, duration_sec=None, generated_at="x",
    )
    assert sc["artifact_present"] is False


def test_count_falsifiable_counts_percentages():
    assert joy._count_falsifiable("70% chance, and 12 % odds, plus 100%") == 3
    assert joy._count_falsifiable("no numbers here") == 0
    assert joy._count_falsifiable("") == 0


# ---- extract block -------------------------------------------------------

def test_extract_block_case_insensitive():
    text = "prelude [ARTIFACT] the thing [/ARTIFACT] mid [reflection] why [/reflection]"
    assert joy._extract_block(text, "ARTIFACT") == "the thing"
    assert joy._extract_block(text, "REFLECTION") == "why"


def test_extract_block_missing_returns_empty():
    assert joy._extract_block("no tags", "ARTIFACT") == ""


# ---- scoped context: no personal data ------------------------------------

def test_joy_context_excludes_personal_files(storage):
    # Plant a "personal" work file the normal worker context would surface.
    fs.write_file("positions/secret.md", "PERSONAL_SECRET_TOKEN in a work position")
    fs.write_file("joy/runs/2026-07-01/reflection.md", "a prior joy reflection")
    activity = {"slug": "swarm-kata", "title": "Swarm Kata", "prompt": "repair a thing"}
    ctx = joy.joy_context(activity)
    assert "Swarm Kata" in ctx
    assert "repair a thing" in ctx
    assert "a prior joy reflection" in ctx  # joy history is fair game
    assert "PERSONAL_SECRET_TOKEN" not in ctx  # work files are NOT


# ---- recent_run_slugs ----------------------------------------------------

def test_recent_run_slugs_most_recent_first(storage):
    for d, slug in [("2026-07-01", "swarm-kata"), ("2026-07-02", "puzzle-relay")]:
        fs.write_file(f"joy/runs/{d}/scorecard.json", json.dumps({"activity": slug}))
    slugs = joy.recent_run_slugs()
    assert slugs == ["puzzle-relay", "swarm-kata"]


def test_recent_run_slugs_skips_bad_json(storage):
    fs.write_file("joy/runs/2026-07-01/scorecard.json", "{not json")
    fs.write_file("joy/runs/2026-07-02/scorecard.json", json.dumps({"activity": "constraint-art"}))
    assert joy.recent_run_slugs() == ["constraint-art"]


# ---- run_joy_session: full loop with fake runners ------------------------

def _fake_runners(synth_text):
    """Return (round_runner, synth_runner) that ignore models and return fakes."""
    seen = {}

    def round_runner(prompt, models, mode, order):
        seen.setdefault("modes", []).append(mode)
        return {m: f"{m} says hi ({mode})" for m in order}

    def synth_runner(query, all_rounds):
        seen["query"] = query
        seen["rounds"] = all_rounds
        return synth_text

    return round_runner, synth_runner, seen


def test_run_joy_session_end_to_end(storage):
    synth = "[ARTIFACT] a haiku about raccoons [/ARTIFACT] [REFLECTION] made a haiku; 65% it rhymes [/REFLECTION]"
    rr, sr, seen = _fake_runners(synth)
    res = joy.run_joy_session(rr, sr, core4_models={"claude": object()}, date_str="2026-07-03")

    assert res["ok"] is True
    assert res["date"] == "2026-07-03"
    # Two rounds ran, parallel then daisy.
    assert seen["modes"] == ["parallel", "daisy"]

    # All five run files persisted.
    base = "joy/runs/2026-07-03"
    for name in ("prompt.md", "transcript.json", "artifact.md", "reflection.md", "scorecard.json"):
        assert fs.read_file(f"{base}/{name}") is not None

    assert fs.read_file(f"{base}/artifact.md") == "a haiku about raccoons"
    assert "made a haiku" in fs.read_file(f"{base}/reflection.md")

    sc = json.loads(fs.read_file(f"{base}/scorecard.json"))
    assert sc["activity"] == res["activity"]
    assert sc["artifact_present"] is True and sc["reflection_present"] is True
    assert sc["falsifiable_claims"] == 1
    assert sc["models"] == list(joy.CORE_4)

    # Reflection is logged for Calibration Casino fuel.
    log = fs.read_file("joy/ideas/reflections-log.md")
    assert log and "2026-07-03" in log


def test_run_joy_session_falls_back_to_synthesis_when_no_artifact_tag(storage):
    rr, sr, _ = _fake_runners("just a plain synthesis with no tags at all")
    res = joy.run_joy_session(rr, sr, core4_models={}, date_str="2026-07-04")
    art = fs.read_file("joy/runs/2026-07-04/artifact.md")
    assert art.startswith("just a plain synthesis")


def test_run_joy_session_marks_new_tool_for_tiny_tool(storage):
    # Seed a registry with ONLY tiny-tool-invention so the pick is forced.
    fs.write_file(
        "joy/activities.md",
        "## Accepted\n\n### tiny-tool-invention — Tiny Tool Invention\nInvent one tool.\n",
    )
    rr, sr, _ = _fake_runners("[ARTIFACT] a tool schema [/ARTIFACT] [REFLECTION] proposed a tool [/REFLECTION]")
    res = joy.run_joy_session(rr, sr, core4_models={}, date_str="2026-07-05")
    assert res["activity"] == "tiny-tool-invention"
    sc = json.loads(fs.read_file("joy/runs/2026-07-05/scorecard.json"))
    assert sc["new_tool_proposed"] is True


def test_run_joy_session_errors_with_no_activities(storage, monkeypatch):
    monkeypatch.setattr(joy, "ensure_activities", lambda: [])
    res = joy.run_joy_session(lambda *a: {}, lambda *a: "", core4_models={}, date_str="2026-07-06")
    assert res["ok"] is False
