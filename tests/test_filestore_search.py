"""Ranking tests for swarm_filestore.search_files.

The old behaviour returned the alphabetically-first N matches (it walked
sorted(rglob) and broke early), so a search returned whichever filenames sorted
earliest rather than the best matches. These pin the ranked behaviour: a
stronger match beats an alphabetically-earlier weak one, filename hits rank
high, recency breaks ties, and max_results is honoured.
"""
import os

import swarm_filestore as fs


def _set_mtime(rel_path: str, when: float) -> None:
    """Force a file's mtime so recency-tiebreak tests are deterministic."""
    target = fs._storage_root() / rel_path
    os.utime(target, (when, when))


def test_best_match_beats_alphabetical_first(storage):
    # 'aaa' sorts first but matches weakly (one late occurrence); 'zzz' sorts
    # last but matches strongly (name + many early occurrences).
    fs.write_file("positions/aaa.md", "intro text\n" * 30 + "a lone pricing mention at the end")
    fs.write_file("positions/zzz-pricing.md", "pricing pricing pricing up front " + "filler " * 40)

    res = fs.search_files("pricing", max_results=5)
    assert res[0]["path"] == "positions/zzz-pricing.md"   # best, not alphabetical-first
    assert res[0]["score"] > res[1]["score"]


def test_name_match_scores_high(storage):
    fs.write_file("positions/pricing-model.md", "unrelated body about raccoons")
    fs.write_file("positions/notes.md", "one passing pricing note " + "x " * 300)

    res = fs.search_files("pricing", max_results=5)
    paths = [r["path"] for r in res]
    assert "positions/pricing-model.md" in paths
    # Filename hit (no content match) is reported as a name match.
    name_hit = next(r for r in res if r["path"] == "positions/pricing-model.md")
    assert name_hit["match_type"] == "name"


def test_recency_breaks_ties(storage):
    # Two files with identical match strength; the newer one must rank first.
    fs.write_file("positions/older.md", "pricing")
    fs.write_file("positions/newer.md", "pricing")
    _set_mtime("positions/older.md", 1_000_000)
    _set_mtime("positions/newer.md", 2_000_000)

    res = fs.search_files("pricing", max_results=5)
    ranked = [r["path"] for r in res]
    assert ranked.index("positions/newer.md") < ranked.index("positions/older.md")


def test_max_results_respected(storage):
    for i in range(8):
        fs.write_file(f"positions/p{i}.md", "pricing appears here")
    res = fs.search_files("pricing", max_results=3)
    assert len(res) == 3


def test_subdir_scopes_and_isnt_starved(storage):
    # Many strong matches in questions/, one weaker match in positions/. A
    # positions-scoped search must still surface the positions/ hit — the old
    # post-truncation filter would have returned nothing here.
    for i in range(8):
        fs.write_file(f"questions/q{i}.md", "pricing pricing pricing pricing")
    fs.write_file("positions/lonely.md", "a single pricing note")

    res = fs.search_files("pricing", max_results=5, subdir="positions")
    assert [r["path"] for r in res] == ["positions/lonely.md"]
    assert all(r["path"].startswith("positions/") for r in res)


def test_no_match_returns_empty(storage):
    fs.write_file("positions/x.md", "nothing relevant here")
    assert fs.search_files("pricing") == []


def test_short_query_rejected(storage):
    fs.write_file("positions/x.md", "a pricing doc")
    assert fs.search_files("p") == []


# ---- nested directory listing (joy/metrics enumeration bug) --------------

def test_list_files_scopes_to_nested_dir(storage):
    fs.write_file("joy/runs/2026-07-03/scorecard.json", "{}")
    fs.write_file("joy/metrics/calibration.json", "{}")
    fs.write_file("joy/activities.md", "roster")

    # Nested path lists ONLY that subtree (previously it listed all of joy/).
    metrics = fs.list_files("joy/metrics")
    assert metrics == ["joy/metrics/calibration.json"]

    runs = fs.list_files("joy/runs")
    assert runs == ["joy/runs/2026-07-03/scorecard.json"]

    # Top lane still lists everything under it.
    assert set(fs.list_files("joy")) == {
        "joy/runs/2026-07-03/scorecard.json",
        "joy/metrics/calibration.json",
        "joy/activities.md",
    }


def test_is_safe_subdir():
    assert fs.is_safe_subdir("") is True
    assert fs.is_safe_subdir("joy") is True
    assert fs.is_safe_subdir("joy/metrics") is True
    assert fs.is_safe_subdir("joy/runs/2026-07-03") is True     # dated run dir allowed
    # Traversal / junk always rejected.
    assert fs.is_safe_subdir("../etc") is False
    assert fs.is_safe_subdir("joy/../positions") is False
    assert fs.is_safe_subdir("9lane/x") is False                # lane must be letter-led
    assert fs.is_safe_subdir("joy/.") is False


def test_list_files_reaches_dated_run_dir(storage):
    fs.write_file("joy/runs/2026-07-03/scorecard.json", "{}")
    fs.write_file("joy/runs/2026-07-04/scorecard.json", "{}")
    assert fs.list_files("joy/runs/2026-07-03") == ["joy/runs/2026-07-03/scorecard.json"]


def test_search_scopes_to_nested_dir(storage):
    fs.write_file("joy/metrics/calibration.json", "pricing appears in metrics")
    fs.write_file("joy/runs/r.md", "pricing appears in a run")
    res = fs.search_files("pricing", subdir="joy/metrics")
    assert [r["path"] for r in res] == ["joy/metrics/calibration.json"]
