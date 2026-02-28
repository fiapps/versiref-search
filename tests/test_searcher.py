"""Tests for the searcher module."""

import pytest

from versiref.search import get_context, search_database


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
