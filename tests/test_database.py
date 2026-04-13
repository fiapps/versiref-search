"""Tests for Database operations."""

import pytest
from versiref.search.database import Database


@pytest.fixture
def db(tmp_path):
    """Open database with schema created."""
    path = tmp_path / "test.db"
    with Database(path) as d:
        d.create_schema()
        yield d


# --- Connection lifecycle ---


def test_context_manager_opens_and_closes(tmp_path):
    path = tmp_path / "test.db"
    with Database(path) as d:
        d.create_schema()
        assert d.conn is not None
    assert d.conn is None


def test_schema_creation_is_idempotent(db):
    db.create_schema()  # second call should not raise


# --- Metadata ---


def test_set_and_get_metadata(db):
    db.set_metadata("title", "My Book")
    assert db.get_metadata("title") == "My Book"


def test_get_missing_metadata_returns_none(db):
    assert db.get_metadata("nonexistent") is None


def test_set_metadata_overwrites(db):
    db.set_metadata("key", "old")
    db.set_metadata("key", "new")
    assert db.get_metadata("key") == "new"


def test_get_all_metadata(db):
    db.set_metadata("a", "1")
    db.set_metadata("b", "2")
    meta = db.get_all_metadata()
    assert meta["a"] == "1"
    assert meta["b"] == "2"


# --- Content blocks ---


def test_insert_content_returns_positive_id(db):
    block_id = db.insert_content("A paragraph")
    assert block_id > 0


def test_insert_content_ids_are_increasing(db):
    id1 = db.insert_content("First")
    id2 = db.insert_content("Second")
    assert id2 > id1


def test_insert_and_retrieve_paragraph(db):
    block_id = db.insert_content("A paragraph", heading_level=None)
    row = db.get_content_by_id(block_id)
    assert row is not None
    _, text, level = row
    assert text == "A paragraph"
    assert level is None


def test_insert_and_retrieve_heading(db):
    block_id = db.insert_content("# Title", heading_level=1)
    _, text, level = db.get_content_by_id(block_id)
    assert text == "# Title"
    assert level == 1


def test_get_content_by_missing_id_returns_none(db):
    assert db.get_content_by_id(999) is None


def test_get_content_range(db):
    id1 = db.insert_content("Block 1")
    id2 = db.insert_content("Block 2")
    id3 = db.insert_content("Block 3")
    rows = db.get_content_range(id1, id3)
    assert len(rows) == 3
    assert [r[1] for r in rows] == ["Block 1", "Block 2", "Block 3"]


def test_get_content_range_partial(db):
    id1 = db.insert_content("Block 1")
    id2 = db.insert_content("Block 2")
    id3 = db.insert_content("Block 3")
    rows = db.get_content_range(id2, id3)
    assert len(rows) == 2
    assert rows[0][1] == "Block 2"


def test_get_content_range_empty(db):
    assert db.get_content_range(100, 200) == []


# --- Reference index ---


def test_insert_reference_returns_positive_id(db):
    block_id = db.insert_content("Text with Lk 1:28.")
    ref_id = db.insert_reference(block_id, 42001028, 42001028, 10, 17)
    assert ref_id > 0


def test_search_exact_verse_match(db):
    block_id = db.insert_content("Lk 1:28 is cited here.")
    db.insert_reference(block_id, 42001028, 42001028, 0, 7)
    results = db.search_by_reference_range(42001028, 42001028)
    assert len(results) == 1
    content_id, block_text, char_start, char_end = results[0]
    assert content_id == block_id
    assert block_text == "Lk 1:28 is cited here."
    assert (char_start, char_end) == (0, 7)


def test_search_query_inside_stored_range(db):
    """Single-verse query overlaps a stored multi-verse reference."""
    block_id = db.insert_content("Lk 1:1-50 cited.")
    db.insert_reference(block_id, 42001001, 42001050, 0, 10)
    results = db.search_by_reference_range(42001028, 42001028)
    assert len(results) == 1


def test_search_stored_inside_query_range(db):
    """Wide query range contains a stored single-verse reference."""
    block_id = db.insert_content("Lk 1:28 cited.")
    db.insert_reference(block_id, 42001028, 42001028, 0, 7)
    results = db.search_by_reference_range(42001001, 42001050)
    assert len(results) == 1


def test_search_no_overlap(db):
    block_id = db.insert_content("Lk 1:28 cited.")
    db.insert_reference(block_id, 42001028, 42001028, 0, 7)
    results = db.search_by_reference_range(42002001, 42002001)
    assert len(results) == 0


def test_search_adjacent_verse_does_not_match(db):
    block_id = db.insert_content("Lk 1:28.")
    db.insert_reference(block_id, 42001028, 42001028, 0, 7)
    results = db.search_by_reference_range(42001029, 42001029)
    assert len(results) == 0


def test_search_reference_range_multiple_blocks(db):
    id1 = db.insert_content("Block with Lk 1:28.")
    id2 = db.insert_content("Block with Lk 1:30.")
    db.insert_reference(id1, 42001028, 42001028, 11, 18)
    db.insert_reference(id2, 42001030, 42001030, 11, 18)
    results = db.search_by_reference_range(42001001, 42001050)
    assert len(results) == 2
    assert [r[0] for r in results] == [id1, id2]


def test_search_reference_range_multiple_matches_in_one_block(db):
    """A block with multiple matching references yields one row per reference."""
    block_id = db.insert_content("Lk 1:28 and later Lk 1:30 are both here.")
    db.insert_reference(block_id, 42001028, 42001028, 0, 7)
    db.insert_reference(block_id, 42001030, 42001030, 18, 25)
    results = db.search_by_reference_range(42001001, 42001050)
    assert len(results) == 2
    assert [(r[2], r[3]) for r in results] == [(0, 7), (18, 25)]


# --- String search ---


def test_search_by_string_found(db):
    block_id = db.insert_content("Mary is mentioned here.")
    results = db.search_by_string("Mary")
    assert any(r[0] == block_id for r in results)


def test_search_by_string_case_insensitive(db):
    block_id = db.insert_content("Mary is mentioned here.")
    results = db.search_by_string("mary")
    assert any(r[0] == block_id for r in results)


def test_search_by_string_not_found(db):
    db.insert_content("Some text here.")
    assert db.search_by_string("nonexistent") == []


def test_search_by_string_returns_highlighted_text(db):
    db.insert_content("Specific content.")
    results = db.search_by_string("Specific")
    assert "<mark>Specific</mark> content." == results[0][1]


def test_search_by_string_word_boundary(db):
    """FTS5 matches whole words, not substrings."""
    db.insert_content("Anna went to the market.")
    db.insert_content("Something soprannaturale happened.")
    results = db.search_by_string("Anna")
    assert len(results) == 1
    assert "<mark>Anna</mark>" in results[0][1]


# --- Heading context ---


def test_get_preceding_heading(db):
    h1_id = db.insert_content("# Chapter One", heading_level=1)
    p_id = db.insert_content("A paragraph.")
    result = db.get_preceding_heading(p_id, 1)
    assert result is not None
    assert result[0] == h1_id


def test_get_preceding_heading_not_present(db):
    p_id = db.insert_content("A paragraph with no preceding heading.")
    assert db.get_preceding_heading(p_id, 1) is None


def test_get_preceding_heading_most_recent(db):
    db.insert_content("# Chapter 1", heading_level=1)
    h2_id = db.insert_content("# Chapter 2", heading_level=1)
    p_id = db.insert_content("Content.")
    result = db.get_preceding_heading(p_id, 1)
    assert result[0] == h2_id


def test_get_all_preceding_headings(db):
    h1_id = db.insert_content("# Chapter", heading_level=1)
    h2_id = db.insert_content("## Section", heading_level=2)
    p_id = db.insert_content("Content.")
    headings = db.get_all_preceding_headings(p_id)
    assert headings[1][0] == h1_id
    assert headings[2][0] == h2_id


def test_get_all_preceding_headings_empty(db):
    p_id = db.insert_content("First block, no headings precede it.")
    assert db.get_all_preceding_headings(p_id) == {}


# --- Counts ---


def test_count_blocks_empty(db):
    assert db.count_content_blocks() == 0


def test_count_blocks(db):
    db.insert_content("Block 1")
    db.insert_content("Block 2")
    assert db.count_content_blocks() == 2


def test_count_references_empty(db):
    assert db.count_references() == 0


def test_count_references(db):
    block_id = db.insert_content("Text")
    db.insert_reference(block_id, 42001028, 42001028, 0, 7)
    db.insert_reference(block_id, 19045010, 19045010, 10, 18)
    assert db.count_references() == 2
