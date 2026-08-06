"""Tests for Database operations."""

import pytest
from versiref.search.database import (
    Database,
    IncompatibleDatabaseError,
    PRODUCT_NAME,
    SCHEMA_VERSION,
    _parse_schema_version,
)


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


# --- Schema validation ---


def _mark(db, *, fmt=PRODUCT_NAME, version=SCHEMA_VERSION):
    """Write the product marker and schema version onto a database."""
    if fmt is not None:
        db.set_metadata("format", fmt)
    if version is not None:
        db.set_metadata("schema_version", version)


def test_validate_schema_accepts_current(db):
    _mark(db)
    db.validate_schema()  # should not raise


def test_validate_schema_missing_format_raises(db):
    _mark(db, fmt=None)
    with pytest.raises(IncompatibleDatabaseError, match="format"):
        db.validate_schema()


def test_validate_schema_wrong_product_raises(db):
    _mark(db, fmt="versiref-bible")
    with pytest.raises(IncompatibleDatabaseError, match="versiref-bible"):
        db.validate_schema()


def test_validate_schema_missing_version_raises(db):
    _mark(db, version=None)
    with pytest.raises(IncompatibleDatabaseError, match="schema_version"):
        db.validate_schema()


def test_validate_schema_unparseable_version_raises(db):
    _mark(db, version="not.a.version")
    with pytest.raises(IncompatibleDatabaseError, match="unparseable"):
        db.validate_schema()


def test_validate_schema_accepts_newer_minor(db):
    # A 2.1 database satisfies code written against 2.0 (additive changes).
    _mark(db, version="2.1")
    db.validate_schema()


def test_validate_schema_rejects_newer_major(db):
    _mark(db, version="3.0")
    with pytest.raises(IncompatibleDatabaseError, match="incompatible"):
        db.validate_schema()


def test_validate_schema_rejects_older_major(db):
    # A 1.x database (8-digit verse keys) must be rejected outright: the 2.0
    # key widening makes its stored keys silently mismatch new queries.
    _mark(db, version="1.1")
    with pytest.raises(IncompatibleDatabaseError, match="re-index"):
        db.validate_schema()


def test_validate_schema_rejects_older_minor(db, monkeypatch):
    # Code requiring 2.1 must reject a 2.0 database that lacks the additions.
    monkeypatch.setattr("versiref.search.database.REQUIRED_SCHEMA_VERSION", "2.1")
    _mark(db, version="2.0")
    with pytest.raises(IncompatibleDatabaseError, match="incompatible"):
        db.validate_schema()


def test_parse_schema_version_valid():
    assert _parse_schema_version("1.0") == (1, 0)
    assert _parse_schema_version("12.34") == (12, 34)


@pytest.mark.parametrize("value", ["1", "1.0.0", "x.y", "1.x", ""])
def test_parse_schema_version_invalid(value):
    with pytest.raises(ValueError):
        _parse_schema_version(value)


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
    ref_id = db.insert_reference(block_id, 4200102800, 4200102800, 10, 17)
    assert ref_id > 0


def test_search_exact_verse_match(db):
    block_id = db.insert_content("Lk 1:28 is cited here.")
    db.insert_reference(block_id, 4200102800, 4200102800, 0, 7)
    results = db.search_by_reference_range(4200102800, 4200102800)
    assert len(results) == 1
    content_id, block_text, char_start, char_end = results[0]
    assert content_id == block_id
    assert block_text == "Lk 1:28 is cited here."
    assert (char_start, char_end) == (0, 7)


def test_search_query_inside_stored_range(db):
    """Single-verse query overlaps a stored multi-verse reference."""
    block_id = db.insert_content("Lk 1:1-50 cited.")
    db.insert_reference(block_id, 4200100100, 4200105000, 0, 10)
    results = db.search_by_reference_range(4200102800, 4200102800)
    assert len(results) == 1


def test_search_stored_inside_query_range(db):
    """Wide query range contains a stored single-verse reference."""
    block_id = db.insert_content("Lk 1:28 cited.")
    db.insert_reference(block_id, 4200102800, 4200102800, 0, 7)
    results = db.search_by_reference_range(4200100100, 4200105000)
    assert len(results) == 1


def test_search_no_overlap(db):
    block_id = db.insert_content("Lk 1:28 cited.")
    db.insert_reference(block_id, 4200102800, 4200102800, 0, 7)
    results = db.search_by_reference_range(4200200100, 4200200100)
    assert len(results) == 0


def test_search_adjacent_verse_does_not_match(db):
    block_id = db.insert_content("Lk 1:28.")
    db.insert_reference(block_id, 4200102800, 4200102800, 0, 7)
    results = db.search_by_reference_range(4200102900, 4200102900)
    assert len(results) == 0


def test_search_reference_range_multiple_blocks(db):
    id1 = db.insert_content("Block with Lk 1:28.")
    id2 = db.insert_content("Block with Lk 1:30.")
    db.insert_reference(id1, 4200102800, 4200102800, 11, 18)
    db.insert_reference(id2, 4200103000, 4200103000, 11, 18)
    results = db.search_by_reference_range(4200100100, 4200105000)
    assert len(results) == 2
    assert [r[0] for r in results] == [id1, id2]


def test_search_reference_range_multiple_matches_in_one_block(db):
    """A block with multiple matching references yields one row per reference."""
    block_id = db.insert_content("Lk 1:28 and later Lk 1:30 are both here.")
    db.insert_reference(block_id, 4200102800, 4200102800, 0, 7)
    db.insert_reference(block_id, 4200103000, 4200103000, 18, 25)
    results = db.search_by_reference_range(4200100100, 4200105000)
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
    db.insert_reference(block_id, 420010280000, 420010280000, 0, 7)
    db.insert_reference(block_id, 1904501000, 1904501000, 10, 18)
    assert db.count_references() == 2


# --- Milestones ---


@pytest.fixture
def db_with_blocks(db):
    """Database with four plain content blocks (ids 1-4)."""
    for i in range(1, 5):
        db.insert_content(f"Paragraph {i}.")
    return db


def test_get_milestone_for_block_before_any_milestone(db_with_blocks):
    db_with_blocks.insert_milestone("page", "53", content_id=2, char_offset=0)
    assert db_with_blocks.get_milestone_for_block(1, "page") is None


def test_get_milestone_for_block_at_and_after_milestone(db_with_blocks):
    db_with_blocks.insert_milestone("page", "53", content_id=2, char_offset=0)
    assert db_with_blocks.get_milestone_for_block(2, "page") == "53"
    assert db_with_blocks.get_milestone_for_block(4, "page") == "53"


def test_get_milestone_for_block_sparse_reports_latest_recorded(db_with_blocks):
    # Sparse page numbers: the latest *recorded* page is reported.
    db_with_blocks.insert_milestone("page", "53", content_id=1, char_offset=0)
    db_with_blocks.insert_milestone("page", "82", content_id=4, char_offset=0)
    assert db_with_blocks.get_milestone_for_block(3, "page") == "53"
    assert db_with_blocks.get_milestone_for_block(4, "page") == "82"


def test_get_milestone_for_block_mid_block_offset(db_with_blocks):
    db_with_blocks.insert_milestone("page", "10", content_id=2, char_offset=8)
    # At the block's start the break has not happened yet.
    assert db_with_blocks.get_milestone_for_block(2, "page") is None
    assert db_with_blocks.get_milestone_for_block(2, "page", char_offset=8) == "10"
    assert db_with_blocks.get_milestone_for_block(3, "page") == "10"


def test_get_milestone_for_block_different_types_are_independent(db_with_blocks):
    db_with_blocks.insert_milestone("page", "53", content_id=2, char_offset=0)
    db_with_blocks.insert_milestone("marg", "667", content_id=3, char_offset=0)
    assert db_with_blocks.get_milestone_for_block(3, "page") == "53"
    assert db_with_blocks.get_milestone_for_block(3, "marg") == "667"
    assert db_with_blocks.get_milestone_for_block(2, "marg") is None


def test_get_milestone_range_spans_to_next_milestone(db_with_blocks):
    db_with_blocks.insert_milestone("page", "53", content_id=2, char_offset=0)
    db_with_blocks.insert_milestone("page", "54", content_id=4, char_offset=5)
    # Page 53 runs from its own block through the block holding the next
    # break (the break falls mid-block, so block 4 belongs to both pages).
    assert db_with_blocks.get_milestone_range("page", "53") == (2, 4)


def test_get_milestone_range_last_one_runs_to_end(db_with_blocks):
    db_with_blocks.insert_milestone("page", "53", content_id=2, char_offset=0)
    assert db_with_blocks.get_milestone_range("page", "53") == (2, 4)


def test_get_milestone_range_missing_value(db_with_blocks):
    db_with_blocks.insert_milestone("page", "53", content_id=2, char_offset=0)
    assert db_with_blocks.get_milestone_range("page", "54") is None


def test_get_milestone_range_for_marg(db_with_blocks):
    db_with_blocks.insert_milestone("marg", "667", content_id=2, char_offset=0)
    db_with_blocks.insert_milestone("marg", "668", content_id=4, char_offset=0)
    assert db_with_blocks.get_milestone_range("marg", "667") == (2, 4)


def test_get_milestone_values_in_document_order(db_with_blocks):
    db_with_blocks.insert_milestone("page", "xvii", content_id=1, char_offset=0)
    db_with_blocks.insert_milestone("page", "1", content_id=2, char_offset=0)
    db_with_blocks.insert_milestone("page", "2", content_id=3, char_offset=0)
    assert db_with_blocks.get_milestone_values("page") == ["xvii", "1", "2"]
    assert db_with_blocks.get_milestone_values("marg") == []


def test_get_milestones_in_range_groups_by_block(db_with_blocks):
    db_with_blocks.insert_milestone("page", "53", content_id=2, char_offset=0)
    db_with_blocks.insert_milestone("page", "54", content_id=2, char_offset=8)
    db_with_blocks.insert_milestone("marg", "667", content_id=3, char_offset=0)
    db_with_blocks.insert_milestone("page", "55", content_id=4, char_offset=0)

    found = db_with_blocks.get_milestones_in_range(2, 3)
    assert list(found) == [2, 3]
    assert [(m.type, m.value, m.offset) for m in found[2]] == [
        ("page", "53", 0),
        ("page", "54", 8),
    ]
    assert [(m.type, m.value) for m in found[3]] == [("marg", "667")]


def test_get_milestones_in_range_filters_types(db_with_blocks):
    db_with_blocks.insert_milestone("page", "53", content_id=2, char_offset=0)
    db_with_blocks.insert_milestone("marg", "667", content_id=2, char_offset=4)
    found = db_with_blocks.get_milestones_in_range(1, 4, types=("marg",))
    assert [m.value for m in found[2]] == ["667"]


def test_get_last_milestone_in_range(db_with_blocks):
    db_with_blocks.insert_milestone("page", "53", content_id=2, char_offset=0)
    db_with_blocks.insert_milestone("page", "54", content_id=2, char_offset=8)
    db_with_blocks.insert_milestone("page", "55", content_id=4, char_offset=0)
    assert db_with_blocks.get_last_milestone_in_range("page", 1, 3) == "54"
    assert db_with_blocks.get_last_milestone_in_range("page", 1, 4) == "55"
    assert db_with_blocks.get_last_milestone_in_range("page", 1, 1) is None
    assert db_with_blocks.get_last_milestone_in_range("marg", 1, 4) is None


def test_count_milestones(db_with_blocks):
    assert db_with_blocks.count_milestones() == 0
    db_with_blocks.insert_milestone("page", "1", content_id=1, char_offset=0)
    assert db_with_blocks.count_milestones() == 1


# --- Commentary scopes ---


def test_search_scopes_overlap(db):
    db.insert_scope(1, 10, 4300705300, 4300801100)  # Jn 7:53-8:11
    db.insert_scope(4, 5, 4300800700, 4300800700)  # Jn 8:7
    # A query inside the narrow scope matches both rows.
    results = db.search_scopes(4300800700, 4300800700)
    assert [(r[1], r[2]) for r in results] == [(1, 10), (4, 5)]
    # A query outside both matches nothing.
    assert db.search_scopes(4300900100, 4300900100) == []


def test_count_scopes(db):
    assert db.count_scopes() == 0
    db.insert_scope(1, 2, 4300800700, 4300800700)
    assert db.count_scopes() == 1


# --- Graceful degradation when optional tables are absent ---


@pytest.fixture
def legacy_db(db_with_blocks):
    """Simulate a database lacking the milestone and commentary_scope tables."""
    db_with_blocks.conn.execute("DROP TABLE milestone")
    db_with_blocks.conn.execute("DROP TABLE commentary_scope")
    db_with_blocks.conn.commit()
    return db_with_blocks


def test_legacy_db_milestone_queries_return_empty(legacy_db):
    assert legacy_db.get_milestone_for_block(1, "page") is None
    assert legacy_db.get_milestone_range("page", "53") is None
    assert legacy_db.get_milestone_values("page") == []
    assert legacy_db.get_milestones_in_range(1, 4) == {}
    assert legacy_db.get_last_milestone_in_range("page", 1, 4) is None
    assert legacy_db.count_milestones() == 0


def test_legacy_db_scope_queries_return_empty(legacy_db):
    assert legacy_db.search_scopes(4300800700, 4300800700) == []
    assert legacy_db.count_scopes() == 0
