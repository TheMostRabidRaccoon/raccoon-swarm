"""Cache + search-path tests for swarm_semantic.

These build a real on-disk index and drive the full search() path, but with a
deterministic *fake* embedder (a tiny bag-of-vocab vector) so no OpenAI call is
made. Needs numpy (a hard runtime dep). Covers: the mtime cache (hit + rebuild
on reindex), metadata pre-filtering, and hybrid keyword blending.
"""
import pytest

pytest.importorskip("numpy")

import swarm_filestore as fs
import swarm_semantic as sem

_VOCAB = ["anansi", "pricing", "governance", "raccoon", "tax", "refund"]


def _fake_vec(text):
    low = (text or "").lower()
    # +0.1 baseline so no vector is all-zeros (avoids a degenerate norm).
    return [float(low.count(w)) + 0.1 for w in _VOCAB]


@pytest.fixture
def corpus(storage, monkeypatch):
    """A small filestore + fake embedder, indexed and ready to search."""
    monkeypatch.setattr(sem, "_embed_batch", lambda texts: [_fake_vec(t) for t in texts])
    monkeypatch.setattr(sem, "_embed_one", lambda text: _fake_vec(text))
    sem._invalidate_search_cache()

    fs.write_file(
        "positions/anansi.md",
        "---\ntype: position\nmodel: Claude\ndate: 2026-05-03\ntags: [pricing, governance]\n---\n"
        "The anansi pricing framework holds under governance review.",
    )
    fs.write_file(
        "positions/tax.md",
        "---\ntype: position\nmodel: Gemini\ndate: 2026-06-01\ntags: [tax]\n---\n"
        "The tax refund calculation for the raccoon estate.",
    )
    fs.write_file(
        "questions/open.md",
        "---\ntype: question\nmodel: Claude\ndate: 2026-06-15\n---\n"
        "Open question about governance of the swarm.",
    )
    summary = sem.reindex(force=True)
    assert summary["ok"] and summary["total_chunks"] >= 3
    return storage


# ---- cache ---------------------------------------------------------------

def test_cache_hit_returns_same_matrix(corpus):
    c1 = sem._get_search_cache()
    m1 = c1["matrix"]
    c2 = sem._get_search_cache()
    # Same underlying object -> no reparse/rebuild happened on the second call.
    assert c2["matrix"] is m1


def test_cache_rebuilds_after_reindex(corpus):
    m1 = sem._get_search_cache()["matrix"]
    # A new file changes the index file (new mtime/size) -> cache must rebuild.
    fs.write_file("frameworks/new.md", "---\ntype: framework\n---\nA new raccoon framework.")
    sem.reindex(force=True)
    m2 = sem._get_search_cache()["matrix"]
    assert m2 is not m1
    assert m2.shape[0] > m1.shape[0]  # more chunks now


# ---- search ranking ------------------------------------------------------

def test_search_ranks_relevant_first(corpus):
    res = sem.search("anansi pricing", top_k=3)
    assert res["ok"]
    assert res["results"][0]["path"] == "positions/anansi.md"
    assert "meta" in res["results"][0]


# ---- metadata filtering --------------------------------------------------

def test_filter_by_model(corpus):
    res = sem.search("governance", top_k=10, filters={"model": "Gemini"})
    assert res["ok"]
    assert all(r["meta"].get("model") == "Gemini" for r in res["results"])
    assert res["filtered_candidates"] >= 1


def test_filter_by_type_and_tag(corpus):
    res = sem.search("pricing", top_k=10, filters={"type": "position", "tag": "governance"})
    assert res["ok"]
    assert [r["path"] for r in res["results"]] == ["positions/anansi.md"]


def test_filter_by_date_after(corpus):
    res = sem.search("governance", top_k=10, filters={"after": "2026-06"})
    assert res["ok"]
    paths = {r["path"] for r in res["results"]}
    assert "positions/anansi.md" not in paths  # dated 2026-05, filtered out


def test_filter_no_candidates_returns_empty(corpus):
    res = sem.search("anything", top_k=5, filters={"model": "NoSuchModel"})
    assert res["ok"] and res["results"] == [] and res["filtered_candidates"] == 0


# ---- hybrid --------------------------------------------------------------

def test_hybrid_flag_reported(corpus):
    res = sem.search("refund", top_k=3, hybrid=True)
    assert res["ok"] and res.get("hybrid") is True
    # The tax file literally contains 'refund' — hybrid should surface it top.
    assert res["results"][0]["path"] == "positions/tax.md"
