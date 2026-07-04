"""Unit tests for swarm_evidence — the M1a evidence catalog.

All synthetic (no Drive), against an in-memory SQLite DB. Covers the schema,
content-hash dedup (export sprawl), idempotent + changed re-catalog, ranked
search with origin filtering, fetch-by-anchor provenance, and citation
resolution (the foundation for M2's citation_gap).
"""
import pytest

import swarm_evidence as ev


@pytest.fixture
def db():
    conn = ev.connect(":memory:")
    yield conn
    conn.close()


_PAPER = (
    "# Emergent Behavior\n\n"
    "The taxonomy of emergent swarm behaviors under pricing pressure.\n\n"
    "## Findings\n\n"
    "Models converge on governance when the anchor rotates.\n"
)


# ---- chunking + hashing (pure) -------------------------------------------

def test_chunk_text_tracks_heading_path_and_offsets():
    chunks = ev.chunk_text(_PAPER)
    assert len(chunks) == 2
    assert chunks[0]["heading_path"] == "Emergent Behavior"
    assert chunks[1]["heading_path"] == "Emergent Behavior > Findings"
    # Offsets are monotonic and non-overlapping enough to locate text.
    assert chunks[0]["char_start"] < chunks[1]["char_start"]


def test_content_hash_normalizes_whitespace():
    a = ev.content_hash("the  quick\n\nbrown   fox")
    b = ev.content_hash("the quick brown fox")
    assert a == b
    assert ev.content_hash("different words") != a


# ---- catalog + dedup -----------------------------------------------------

def test_catalog_creates_source_and_chunks(db):
    r = ev.catalog_source(db, title="Paper 2", text=_PAPER, origin=ev.CONDUCTOR, external_id="drive:aaa")
    assert r["status"] == "created" and r["chunks"] == 2
    assert r["canonical_source_id"] == r["source_id"]
    assert ev.stats(db)["by_origin"] == {ev.CONDUCTOR: 1}


def test_content_dedup_links_canonical_and_skips_reindex(db):
    ev.catalog_source(db, title="Paper 2", text=_PAPER, origin=ev.CONDUCTOR, external_id="drive:aaa")
    # Same words, different whitespace + title (a .txt export of the same doc).
    dup = ev.catalog_source(db, title="Paper 2 (export)",
                            text=_PAPER.replace("\n\n", "\n   \n"),
                            origin=ev.CONDUCTOR, external_id="drive:bbb")
    assert dup["status"] == "duplicate" and dup["is_duplicate"] is True
    assert dup["canonical_source_id"] != dup["source_id"]
    assert dup["chunks"] == 0                    # not re-indexed
    s = ev.stats(db)
    assert s["sources"] == 2 and s["duplicates"] == 1 and s["canonical"] == 1 and s["chunks"] == 2


def test_recatalog_same_content_is_unchanged(db):
    ev.catalog_source(db, title="P", text=_PAPER, origin=ev.CONDUCTOR, external_id="drive:aaa")
    again = ev.catalog_source(db, title="P", text=_PAPER, origin=ev.CONDUCTOR, external_id="drive:aaa")
    assert again["status"] == "unchanged" and again["chunks"] == 0
    assert ev.stats(db)["sources"] == 1


def test_recatalog_changed_content_updates_and_rechunks(db):
    first = ev.catalog_source(db, title="P", text=_PAPER, origin=ev.CONDUCTOR, external_id="drive:aaa")
    changed = ev.catalog_source(db, title="P v2", text=_PAPER + "\n\n## New\n\nAdded a section.\n",
                                origin=ev.CONDUCTOR, external_id="drive:aaa")
    assert changed["status"] == "updated"
    assert changed["source_id"] == first["source_id"]     # same row, re-chunked
    assert changed["chunks"] == 3
    # Old chunks are gone (no stale index rows).
    assert ev.stats(db)["chunks"] == 3


def test_catalog_rejects_bad_origin(db):
    with pytest.raises(ValueError):
        ev.catalog_source(db, title="x", text="y", origin="made-up")


# ---- search --------------------------------------------------------------

def test_search_returns_cited_excerpt(db):
    r = ev.catalog_source(db, title="Paper 2", text=_PAPER, origin=ev.CONDUCTOR, external_id="drive:aaa")
    hits = ev.search(db, "governance", k=5)
    assert hits and hits[0]["title"] == "Paper 2"
    assert hits[0]["origin"] == ev.CONDUCTOR
    assert "governance" in hits[0]["snippet"].lower()
    # A hit is a citable anchor.
    assert hits[0]["source_id"] == r["source_id"] and "content_hash" in hits[0]


def test_search_excludes_duplicates(db):
    ev.catalog_source(db, title="canonical", text=_PAPER, origin=ev.CONDUCTOR, external_id="a")
    ev.catalog_source(db, title="dup", text=_PAPER, origin=ev.CONDUCTOR, external_id="b")
    titles = {h["title"] for h in ev.search(db, "governance", k=10)}
    assert titles == {"canonical"}          # the duplicate carries no chunks


def test_search_origin_filter(db):
    ev.catalog_source(db, title="mine", text="a note about pricing governance", origin=ev.CONDUCTOR, external_id="a")
    ev.catalog_source(db, title="ours", text="a swarm synthesis on pricing governance", origin=ev.SWARM, external_id="b")
    only_third = ev.search(db, "pricing", k=10, origins=(ev.THIRD_PARTY,))
    assert only_third == []
    only_conductor = ev.search(db, "pricing", k=10, origins=(ev.CONDUCTOR,))
    assert {h["origin"] for h in only_conductor} == {ev.CONDUCTOR}


def test_search_empty_query(db):
    ev.catalog_source(db, title="x", text=_PAPER, origin=ev.CONDUCTOR, external_id="a")
    assert ev.search(db, "   ") == []
    assert ev.search(db, "!!!") == []       # punctuation-only can't crash FTS


# ---- fetch + citation resolution -----------------------------------------

def test_fetch_returns_provenance(db):
    r = ev.catalog_source(db, title="Paper 2", text=_PAPER, origin=ev.CONDUCTOR, external_id="a")
    exc = ev.fetch(db, r["source_id"], 1)
    assert exc["heading_path"] == "Emergent Behavior > Findings"
    assert exc["origin"] == ev.CONDUCTOR
    assert "governance" in exc["text"].lower()
    assert ev.fetch(db, r["source_id"], 99) is None


def test_resolve_citation_states(db):
    r = ev.catalog_source(db, title="P", text=_PAPER, origin=ev.CONDUCTOR, external_id="a")
    h = ev.fetch(db, r["source_id"], 0)["content_hash"]

    ok = ev.resolve_citation(db, r["source_id"], h, 0)
    assert ok["ok"] is True and ok["reason"] == "resolved"

    missing = ev.resolve_citation(db, r["source_id"], h, 99)
    assert missing["ok"] is False and missing["reason"] == "not-found"

    stale = ev.resolve_citation(db, r["source_id"], "deadbeef", 0)
    assert stale["ok"] is False and stale["reason"] == "stale" and stale["excerpt"] is not None


# ---- anti-laundering primitive -------------------------------------------

def test_independence_primitive():
    assert ev.is_independent_corroborator(ev.SWARM) is False
    assert ev.is_independent_corroborator(ev.CONDUCTOR) is True
    assert ev.is_independent_corroborator(ev.THIRD_PARTY) is True


# ---- LIKE fallback (no FTS5) still works ---------------------------------

# ---- ingest planning (Drive folder → catalog) ----------------------------

_LSJSON = [
    {"Path": "Paper 2/taxonomy.md", "Name": "taxonomy.md", "MimeType": "text/markdown",
     "Size": 900, "ModTime": "2026-04-18T00:00:00Z", "ID": "id-a", "IsDir": False},
    {"Path": "_Notes & Sessions/loop_synthesis_96.docx", "Name": "loop_synthesis_96.docx",
     "MimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
     "Size": 5000, "ID": "id-b", "IsDir": False},
    {"Path": "Paper 2", "Name": "Paper 2", "MimeType": "application/vnd.google-apps.folder",
     "IsDir": True},
    {"Path": "images/diagram.png", "Name": "diagram.png", "MimeType": "image/png",
     "Size": 12000, "ID": "id-c", "IsDir": False},
]


def test_classify_origin():
    assert ev.classify_origin("Paper 2/x.md", "x.md") == ev.CONDUCTOR
    assert ev.classify_origin("_Notes & Sessions/s.md", "s.md") == ev.SWARM
    assert ev.classify_origin("Paper 2/loop_synthesis_5.docx", "loop_synthesis_5.docx") == ev.SWARM
    # Shared-with-me or foreign owner → third-party (untrusted, independent).
    assert ev.classify_origin("x/y.md", "y.md", shared_with_me=True) == ev.THIRD_PARTY
    assert ev.classify_origin("x/y.md", "y.md", owner="someone@else.org",
                              conductor_email="kad@rri.org") == ev.THIRD_PARTY


def test_is_ingestable():
    assert ev.is_ingestable("text/markdown")
    assert ev.is_ingestable("application/vnd.google-apps.document")
    assert ev.is_ingestable("", "notes.txt")
    assert not ev.is_ingestable("image/png", "diagram.png")
    assert not ev.is_ingestable("application/vnd.google-apps.folder")


def test_plan_ingest_drops_dirs_and_classifies():
    recs = ev.plan_ingest(_LSJSON)
    # Folder dropped; 3 files remain.
    assert len(recs) == 3
    by_path = {r["path"]: r for r in recs}
    assert by_path["Paper 2/taxonomy.md"]["origin"] == ev.CONDUCTOR
    assert by_path["Paper 2/taxonomy.md"]["ingestable"] is True
    assert by_path["_Notes & Sessions/loop_synthesis_96.docx"]["origin"] == ev.SWARM
    assert by_path["images/diagram.png"]["ingestable"] is False   # png not text
    assert by_path["Paper 2/taxonomy.md"]["external_id"] == "id-a"


def test_build_manifest_is_metadata_only():
    manifest = ev.build_manifest(ev.plan_ingest(_LSJSON))
    assert manifest["total_files"] == 3
    assert manifest["ingestable"] == 2                # md + docx, not the png
    assert manifest["skipped_non_text"] == 1
    assert manifest["by_origin"] == {ev.CONDUCTOR: 1, ev.SWARM: 1}
    # The manifest names files but carries NO body content (review surface).
    assert all(set(f) == {"path", "origin", "mime_type", "size"} for f in manifest["files"])


def test_ingest_records_with_injected_reader(db):
    recs = ev.plan_ingest(_LSJSON)
    bodies = {
        "Paper 2/taxonomy.md": "# Taxonomy\n\nEmergent behaviors under pricing governance.",
        "_Notes & Sessions/loop_synthesis_96.docx": "Session 96 synthesis: the swarm decided X.",
    }
    summary = ev.ingest_records(db, recs, lambda r: bodies.get(r["path"], ""))
    assert summary["created"] == 2
    assert summary["skipped"] == 1                    # the png (non-ingestable)
    # Origin survived into the catalog: the session doc is swarm-authored.
    hits = ev.search(db, "synthesis", k=5, origins=(ev.SWARM,))
    assert hits and hits[0]["origin"] == ev.SWARM
    # And it's excluded when we ask only for independent (conductor) evidence.
    assert ev.search(db, "synthesis", k=5, origins=(ev.CONDUCTOR,)) == []


def test_ingest_records_skips_empty_bodies(db):
    recs = ev.plan_ingest(_LSJSON)
    summary = ev.ingest_records(db, recs, lambda r: "")   # reader returns nothing
    assert summary["created"] == 0 and summary["skipped"] == 3


def test_search_like_fallback(monkeypatch):
    # Force the FTS5-free path end to end (schema + index + search).
    monkeypatch.setattr(ev, "_fts5_available", lambda: False)
    conn = ev.connect(":memory:")
    try:
        ev.catalog_source(conn, title="P", text=_PAPER, origin=ev.CONDUCTOR, external_id="a")
        hits = ev.search(conn, "governance", k=5)
        assert hits and hits[0]["title"] == "P"
        assert "governance" in hits[0]["snippet"].lower()
    finally:
        conn.close()
