"""Tests for the metadata layer of swarm_semantic: frontmatter parsing,
meta derivation, filter matching, and the keyword signal. All stdlib-only —
no numpy, no OpenAI — so they run in CI on a bare interpreter.
"""
import swarm_semantic as sem


# ---- frontmatter parsing -------------------------------------------------

def test_parse_basic_frontmatter():
    text = (
        "---\n"
        "type: position\n"
        "model: Claude\n"
        "date: 2026-05-03\n"
        "status: active\n"
        "---\n"
        "# body here\n"
    )
    meta = sem._parse_frontmatter(text)
    assert meta["type"] == "position"
    assert meta["model"] == "Claude"
    assert meta["date"] == "2026-05-03"
    assert meta["status"] == "active"


def test_parse_inline_and_block_lists():
    inline = "---\ntags: [governance, persistence]\n---\nbody"
    assert sem._parse_frontmatter(inline)["tags"] == ["governance", "persistence"]
    block = "---\ntags:\n  - governance\n  - persistence\n---\nbody"
    assert sem._parse_frontmatter(block)["tags"] == ["governance", "persistence"]


def test_parse_strips_quotes():
    text = "---\nsource: \"session-104\"\n---\nx"
    assert sem._parse_frontmatter(text)["source"] == "session-104"


def test_no_frontmatter_returns_empty():
    assert sem._parse_frontmatter("# just a heading\nno fences") == {}
    assert sem._parse_frontmatter("") == {}


# ---- meta derivation -----------------------------------------------------

def test_derive_meta_adds_dir_and_type():
    meta = sem._derive_meta("positions/anansi.md", "no frontmatter body")
    assert meta["dir"] == "positions"
    assert meta["type"] == "position"  # derived from dir


def test_derive_meta_frontmatter_type_wins():
    text = "---\ntype: framework\n---\nbody"
    meta = sem._derive_meta("positions/x.md", text)
    assert meta["type"] == "framework"  # explicit beats dir-derived


def test_derive_meta_normalizes_tags_lowercase_list():
    text = "---\ntags: [Governance, Persistence]\n---\nbody"
    meta = sem._derive_meta("questions/q.md", text)
    assert meta["tags"] == ["governance", "persistence"]


# ---- filter matching -----------------------------------------------------

def test_empty_filters_match_everything():
    assert sem._chunk_matches_filters({"type": "position"}, None) is True
    assert sem._chunk_matches_filters({}, {}) is True


def test_exact_field_match_case_insensitive():
    meta = {"model": "Claude", "type": "position"}
    assert sem._chunk_matches_filters(meta, {"model": "claude"}) is True
    assert sem._chunk_matches_filters(meta, {"model": "gemini"}) is False


def test_missing_field_fails_closed():
    assert sem._chunk_matches_filters({"type": "position"}, {"model": "claude"}) is False


def test_tag_membership():
    meta = {"tags": ["governance", "persistence"]}
    assert sem._chunk_matches_filters(meta, {"tag": "governance"}) is True
    assert sem._chunk_matches_filters(meta, {"tags": ["governance", "persistence"]}) is True
    assert sem._chunk_matches_filters(meta, {"tag": "pricing"}) is False


def test_date_after_before():
    meta = {"date": "2026-05-10"}
    assert sem._chunk_matches_filters(meta, {"after": "2026-05"}) is True
    assert sem._chunk_matches_filters(meta, {"before": "2026-05-01"}) is False
    assert sem._chunk_matches_filters(meta, {"after": "2026-01", "before": "2026-12"}) is True


def test_date_filter_without_date_fails():
    assert sem._chunk_matches_filters({"type": "position"}, {"after": "2026-01"}) is False


# ---- keyword fraction ----------------------------------------------------

def test_keyword_frac():
    assert sem._keyword_frac("anansi pricing", "the anansi pricing model") == 1.0
    assert sem._keyword_frac("anansi pricing", "only anansi here") == 0.5
    assert sem._keyword_frac("anansi pricing", "nothing relevant") == 0.0
    assert sem._keyword_frac("", "anything") == 0.0
