"""Tests for the searcher module."""

from unittest.mock import patch, MagicMock

import pytest

from versiref.search import (
    AmbiguousSectionError,
    IncompatibleDatabaseError,
    SectionTooLargeError,
    get_context,
    get_section_by_block,
    get_section_by_heading,
    get_toc,
    index_document,
    search_database,
)
from versiref.search.database import Database


@pytest.fixture
def multi_section_db(tmp_path, ref_style):
    """Build a database with two sibling level-2 sections under two level-1 chapters.

    Block layout:
      1  # Chapter One        (h1)
      2  Intro paragraph.
      3  ## Reading           (h2)
      4  First reading paragraph.
      5  ## Reading           (h2)
      6  Second reading paragraph.
      7  # Chapter Two         (h1)
      8  Chapter two paragraph.
    """
    content = (
        "# Chapter One\n\n"
        "Intro paragraph.\n\n"
        "## Reading\n\n"
        "First reading paragraph.\n\n"
        "## Reading\n\n"
        "Second reading paragraph.\n\n"
        "# Chapter Two\n\n"
        "Chapter two paragraph.\n"
    )
    md = tmp_path / "multi.md"
    md.write_text(content, encoding="utf-8")
    db = tmp_path / "multi.db"
    index_document(
        input_path=md,
        output_path=db,
        metadata={"title": "Multi", "versification": "eng", "lang": "en"},
        ref_style=ref_style,
    )
    return db


# --- Error cases ---


def test_no_query_raises(indexed_db, ref_style):
    with pytest.raises(ValueError, match="At least one"):
        search_database(indexed_db, ref_style)


def test_missing_db_raises(tmp_path, ref_style):
    with pytest.raises(FileNotFoundError):
        search_database(tmp_path / "nonexistent.db", ref_style, string_query="text")


def test_invalid_reference_raises(indexed_db, ref_style):
    with pytest.raises(ValueError):
        search_database(indexed_db, ref_style, reference_query="NotABook 99:99")


@pytest.fixture
def unmarked_db(tmp_path):
    """A schema-correct database with no 'format' marker (legacy-style)."""
    path = tmp_path / "unmarked.db"
    with Database(path) as db:
        db.create_schema()
        db.set_metadata("schema_version", "1.0")
        db.set_metadata("versification_scheme", "eng")
    return path


def test_search_rejects_unmarked_db(unmarked_db, ref_style):
    with pytest.raises(IncompatibleDatabaseError, match="format"):
        search_database(unmarked_db, ref_style, string_query="text")


def test_toc_rejects_unmarked_db(unmarked_db):
    with pytest.raises(IncompatibleDatabaseError, match="format"):
        get_toc(unmarked_db)


def test_context_rejects_unmarked_db(unmarked_db):
    with pytest.raises(IncompatibleDatabaseError, match="format"):
        get_context(unmarked_db, 1, 1)


# --- Reference search ---


def test_reference_search_finds_correct_block(indexed_db, ref_style):
    results = search_database(indexed_db, ref_style, reference_query="Lk 1:28")
    assert len(results) == 1
    assert "Lk 1:28" in results[0].block_text


def test_reference_search_second_reference(indexed_db, ref_style):
    results = search_database(indexed_db, ref_style, reference_query="Ps 45:10")
    assert len(results) == 1
    assert "Ps 45:10" in results[0].block_text


def test_reference_search_no_match(indexed_db, ref_style):
    results = search_database(indexed_db, ref_style, reference_query="Jn 3:16")
    assert results == []


def test_reference_search_range_overlap(indexed_db, ref_style):
    """A verse-range query matches a point reference that falls within it."""
    results = search_database(indexed_db, ref_style, reference_query="Lk 1:1-50")
    assert any("Lk 1:28" in r.block_text for r in results)


def test_reference_search_highlights_match(indexed_db, ref_style):
    """Reference-only hits wrap the cited reference in <mark> tags."""
    results = search_database(indexed_db, ref_style, reference_query="Lk 1:28")
    assert len(results) == 1
    assert "<mark>Lk 1:28</mark>" in results[0].block_text


# --- String search ---


def test_string_search_found(indexed_db, ref_style):
    # "paragraph" appears in all three body paragraphs of minimal_md
    results = search_database(indexed_db, ref_style, string_query="paragraph")
    assert len(results) == 3


def test_string_search_case_insensitive(indexed_db, ref_style):
    lower = search_database(indexed_db, ref_style, string_query="paragraph")
    upper = search_database(indexed_db, ref_style, string_query="PARAGRAPH")
    assert len(lower) == len(upper)


def test_string_search_no_match(indexed_db, ref_style):
    results = search_database(indexed_db, ref_style, string_query="xyznotfound")
    assert results == []


def test_string_search_highlights(indexed_db, ref_style):
    """String search results contain <mark> tags around matches."""
    results = search_database(indexed_db, ref_style, string_query="paragraph")
    assert len(results) > 0
    for result in results:
        assert "<mark>paragraph</mark>" in result.block_text.lower()


# --- Combined search ---


def test_combined_search_union(indexed_db, ref_style):
    # reference finds Lk 1:28 block; string finds Ps 45:10 block — distinct blocks
    results = search_database(
        indexed_db, ref_style, reference_query="Lk 1:28", string_query="Ps"
    )
    assert len(results) == 2


def test_combined_search_prefers_highlighted(indexed_db, ref_style):
    """When both queries match the same block, the highlighted version is used."""
    results = search_database(
        indexed_db, ref_style, reference_query="Lk 1:28", string_query="Opening"
    )
    assert len(results) == 1
    assert "<mark>" in results[0].block_text


# --- Heading context ---


def test_include_headings_true(indexed_db, ref_style):
    # Ps 45:10 block is under "# Chapter One" and "## Section A"
    results = search_database(
        indexed_db, ref_style, reference_query="Ps 45:10", include_headings=True
    )
    assert len(results) == 1
    ctx = results[0].heading_context
    assert 1 in ctx  # Chapter One
    assert 2 in ctx  # Section A


def test_include_headings_false(indexed_db, ref_style):
    results = search_database(
        indexed_db, ref_style, reference_query="Ps 45:10", include_headings=False
    )
    assert len(results) == 1
    assert results[0].heading_context == {}


def test_results_in_document_order(indexed_db, ref_style):
    results = search_database(indexed_db, ref_style, string_query="paragraph")
    ids = [r.block_id for r in results]
    assert ids == sorted(ids)


# --- Block-range limits (start_id / end_id) ---


def test_start_id_excludes_earlier_matches(indexed_db, ref_style):
    """A start_id past the matching block yields no results."""
    # Lk 1:28 is in block 2
    results = search_database(
        indexed_db, ref_style, reference_query="Lk 1:28", start_id=3
    )
    assert results == []


def test_end_id_excludes_later_matches(indexed_db, ref_style):
    """An end_id before the matching block yields no results."""
    # Ps 45:10 is in block 4
    results = search_database(
        indexed_db, ref_style, reference_query="Ps 45:10", end_id=3
    )
    assert results == []


def test_start_and_end_include_match(indexed_db, ref_style):
    """A range that brackets the matching block returns it."""
    results = search_database(
        indexed_db, ref_style, reference_query="Ps 45:10", start_id=3, end_id=5
    )
    assert len(results) == 1
    assert results[0].block_id == 4


def test_string_search_limited_by_range(indexed_db, ref_style):
    """String search honors start_id/end_id — only blocks in range are returned."""
    # "paragraph" appears in blocks 2, 4, and 5. Restricting to 4-5 yields 2.
    results = search_database(
        indexed_db, ref_style, string_query="paragraph", start_id=4, end_id=5
    )
    assert len(results) == 2
    assert [r.block_id for r in results] == [4, 5]


def test_start_id_alone(indexed_db, ref_style):
    """Only start_id given — no upper bound."""
    results = search_database(
        indexed_db, ref_style, string_query="paragraph", start_id=4
    )
    assert [r.block_id for r in results] == [4, 5]


def test_end_id_alone(indexed_db, ref_style):
    """Only end_id given — no lower bound."""
    results = search_database(indexed_db, ref_style, string_query="paragraph", end_id=2)
    assert [r.block_id for r in results] == [2]


def test_start_id_greater_than_end_id_raises(indexed_db, ref_style):
    with pytest.raises(ValueError, match="start_id"):
        search_database(
            indexed_db, ref_style, string_query="paragraph", start_id=5, end_id=2
        )


# --- get_context ---


def test_get_context_full_range(indexed_db):
    blocks = get_context(indexed_db, start_id=1, end_id=5, include_headings=False)
    assert len(blocks) == 5


def test_get_context_partial_range(indexed_db):
    blocks = get_context(indexed_db, start_id=2, end_id=4, include_headings=False)
    assert len(blocks) == 3
    assert all(2 <= b.id <= 4 for b in blocks)


def test_get_context_with_headings(indexed_db):
    # Block 4 is the Ps 45:10 paragraph; it has h1 and h2 headings preceding it
    blocks = get_context(indexed_db, start_id=4, end_id=4, include_headings=True)
    heading_blocks = [b for b in blocks if b.heading_level is not None]
    assert len(heading_blocks) == 2


def test_get_context_without_headings(indexed_db):
    blocks = get_context(indexed_db, start_id=4, end_id=4, include_headings=False)
    assert all(b.heading_level is None for b in blocks)


def test_get_context_empty_range(indexed_db):
    blocks = get_context(indexed_db, start_id=100, end_id=200, include_headings=False)
    assert blocks == []


def test_get_context_missing_db(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_context(tmp_path / "nonexistent.db", start_id=1, end_id=5)


# --- get_section_by_block ---
# indexed_db layout: 1 "# Chapter One", 2 para (Lk 1:28), 3 "## Section A",
# 4 para (Ps 45:10), 5 para.


def test_section_by_block_returns_whole_section(indexed_db):
    blocks = get_section_by_block(indexed_db, block_id=4, level=2)
    assert [b.id for b in blocks] == [3, 4, 5]
    assert blocks[0].heading_level == 2


def test_section_by_block_level_one_spans_document(indexed_db):
    blocks = get_section_by_block(indexed_db, block_id=2, level=1)
    assert [b.id for b in blocks] == [1, 2, 3, 4, 5]


def test_section_by_block_not_under_requested_level(indexed_db):
    # Block 2 sits under the h1 only; there is no enclosing h2.
    with pytest.raises(ValueError, match="not within a level-2 section"):
        get_section_by_block(indexed_db, block_id=2, level=2)


def test_section_by_block_include_headings_prepends_ancestors(indexed_db):
    blocks = get_section_by_block(
        indexed_db, block_id=4, level=2, include_headings=True
    )
    # h1 (block 1) is prepended; the section itself opens with h2 (block 3).
    assert [b.id for b in blocks] == [1, 3, 4, 5]
    assert blocks[0].heading_level == 1


def test_section_by_block_too_large_raises(indexed_db):
    with pytest.raises(SectionTooLargeError) as exc:
        get_section_by_block(indexed_db, block_id=2, level=1, max_blocks=2)
    assert exc.value.block_count == 5
    assert exc.value.max_blocks == 2


def test_section_by_block_invalid_level(indexed_db):
    with pytest.raises(ValueError, match="level must be between 1 and 6"):
        get_section_by_block(indexed_db, block_id=4, level=0)


def test_section_by_block_end_before_start(indexed_db):
    with pytest.raises(ValueError, match="must not be less than"):
        get_section_by_block(indexed_db, block_id=4, level=2, end_id=2)


def test_section_by_block_missing_db(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_section_by_block(tmp_path / "nope.db", block_id=1, level=1)


# --- get_section_by_block boundary behaviour (multi_section_db) ---


def test_section_stops_at_sibling_heading(multi_section_db):
    # Block 4 is under the first "## Reading" (block 3); the section ends
    # before the next h2 at block 5.
    blocks = get_section_by_block(multi_section_db, block_id=4, level=2)
    assert [b.id for b in blocks] == [3, 4]


def test_section_stops_at_shallower_heading(multi_section_db):
    # Block 6 is under the second "## Reading" (block 5); a level-1 heading
    # (block 7) closes it even though it is shallower than the section level.
    blocks = get_section_by_block(multi_section_db, block_id=6, level=2)
    assert [b.id for b in blocks] == [5, 6]


def test_section_by_block_span_multiple(multi_section_db):
    # Spanning blocks 4..6 pulls both "## Reading" sections, stopping at the
    # level-1 heading (block 7).
    blocks = get_section_by_block(multi_section_db, block_id=4, level=2, end_id=6)
    assert [b.id for b in blocks] == [3, 4, 5, 6]


# --- get_section_by_heading ---


def test_section_by_heading_returns_section(indexed_db):
    blocks = get_section_by_heading(indexed_db, "Section A", level=2)
    assert [b.id for b in blocks] == [3, 4, 5]


def test_section_by_heading_case_insensitive(indexed_db):
    blocks = get_section_by_heading(indexed_db, "section a", level=2)
    assert [b.id for b in blocks] == [3, 4, 5]


def test_section_by_heading_no_match(indexed_db):
    with pytest.raises(ValueError, match="No level-2 heading matches"):
        get_section_by_heading(indexed_db, "Nonexistent", level=2)


def test_section_by_heading_ambiguous(multi_section_db):
    with pytest.raises(AmbiguousSectionError) as exc:
        get_section_by_heading(multi_section_db, "Reading", level=2)
    assert [c.id for c in exc.value.candidates] == [3, 5]


def test_section_by_heading_invalid_level(indexed_db):
    with pytest.raises(ValueError, match="level must be between 1 and 6"):
        get_section_by_heading(indexed_db, "Section A", level=7)


# --- get_toc ---


def test_get_toc_default_depth(indexed_db):
    """Default depth=2 returns both h1 and h2 headings from minimal_md."""
    toc = get_toc(indexed_db)
    assert [(b.id, b.heading_level, b.text) for b in toc] == [
        (1, 1, "# Chapter One"),
        (3, 2, "## Section A"),
    ]


def test_get_toc_depth_one(indexed_db):
    """Depth=1 only includes h1 headings."""
    toc = get_toc(indexed_db, depth=1)
    assert [b.id for b in toc] == [1]


def test_get_toc_respects_range(indexed_db):
    """start_id / end_id narrow the toc to the given block range."""
    toc = get_toc(indexed_db, start_id=2)
    assert [b.id for b in toc] == [3]
    toc = get_toc(indexed_db, end_id=2)
    assert [b.id for b in toc] == [1]


def test_get_toc_invalid_depth(indexed_db):
    with pytest.raises(ValueError, match="depth"):
        get_toc(indexed_db, depth=0)
    with pytest.raises(ValueError, match="depth"):
        get_toc(indexed_db, depth=7)


def test_get_toc_start_gt_end(indexed_db):
    with pytest.raises(ValueError, match="start_id"):
        get_toc(indexed_db, start_id=5, end_id=2)


def test_get_toc_missing_db(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_toc(tmp_path / "nonexistent.db")


# --- Versification mapping ---


def test_query_versification_none_uses_db_scheme(indexed_db, ref_style):
    """Default query_versification=None uses the database's own scheme."""
    results = search_database(
        indexed_db, ref_style, reference_query="Lk 1:28", query_versification=None
    )
    assert len(results) == 1
    assert "Lk 1:28" in results[0].block_text


def test_query_versification_same_as_db(indexed_db, ref_style):
    """When query_versification matches the db scheme, no mapping is needed."""
    results = search_database(
        indexed_db, ref_style, reference_query="Lk 1:28", query_versification="eng"
    )
    assert len(results) == 1
    assert "Lk 1:28" in results[0].block_text


def test_query_versification_different_from_db(tmp_path, ref_style):
    """When query_versification differs, the reference is mapped to the db scheme."""
    from versiref import Versification, RefParser
    from versiref.search import index_document

    # Index a document using lxx versification.
    # In LXX, Ps 22:1 corresponds to eng Ps 23:1.
    md_path = tmp_path / "lxx_test.md"
    md_path.write_text("# Test\n\nA paragraph citing Ps 22:1.\n", encoding="utf-8")
    db_path = tmp_path / "lxx_test.db"

    # Build a parser for lxx to verify the reference parses there
    v_lxx = Versification.named("lxx")
    p = RefParser(ref_style, v_lxx)
    ref = p.parse("Ps 22:1")
    assert ref is not None

    index_document(
        input_path=md_path,
        output_path=db_path,
        metadata={"title": "LXX Test", "versification": "lxx", "lang": "en"},
        ref_style=ref_style,
    )

    # Search using eng versification for Ps 23:1 — should map to lxx Ps 22:1
    results = search_database(
        db_path, ref_style, reference_query="Ps 23:1", query_versification="eng"
    )
    assert len(results) == 1
    assert "Ps 22:1" in results[0].block_text


def test_query_versification_map_to_returns_none(indexed_db, ref_style):
    """When map_to() returns None, a ValueError is raised."""
    with patch("versiref.search.searcher.RefParser") as mock_parser_cls:
        mock_ref = MagicMock()
        mock_ref.map_to.return_value = None
        mock_parser = MagicMock()
        mock_parser.parse.return_value = mock_ref
        mock_parser_cls.return_value = mock_parser

        with pytest.raises(ValueError, match="Could not map reference"):
            search_database(
                indexed_db,
                ref_style,
                reference_query="Ps 23:1",
                query_versification="lxx",
            )
