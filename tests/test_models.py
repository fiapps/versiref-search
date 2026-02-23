"""Tests for data models."""

from versiref.search.models import BlockInfo, Hit, SearchResult


def test_hit_attributes():
    hit = Hit(start_pos=10, end_pos=20)
    assert hit.start_pos == 10
    assert hit.end_pos == 20


def test_hit_equality():
    assert Hit(5, 10) == Hit(5, 10)
    assert Hit(5, 10) != Hit(5, 11)
    assert Hit(5, 10) != Hit(4, 10)


def test_block_info_defaults_to_no_heading():
    block = BlockInfo(id=1, text="Some text")
    assert block.heading_level is None


def test_block_info_heading():
    block = BlockInfo(id=2, text="# Title", heading_level=1)
    assert block.heading_level == 1


def test_format_basic():
    result = SearchResult(
        block_id=5,
        block_text="Some text with a reference.",
        hits=[Hit(15, 24)],
        heading_context={},
    )
    output = result.format_for_display()
    assert "[Block 5]" in output
    assert "Some text with a reference." in output
    assert "15-24" in output


def test_format_shows_heading_context():
    result = SearchResult(
        block_id=5,
        block_text="Content.",
        hits=[Hit(0, 7)],
        heading_context={
            1: BlockInfo(id=1, text="# Top Heading", heading_level=1),
            2: BlockInfo(id=3, text="## Sub Heading", heading_level=2),
        },
    )
    output = result.format_for_display(show_headings=True)
    assert "Top Heading" in output
    assert "Sub Heading" in output
    assert "Content." in output


def test_format_suppresses_headings():
    result = SearchResult(
        block_id=5,
        block_text="Content.",
        hits=[Hit(0, 7)],
        heading_context={
            1: BlockInfo(id=1, text="# Top Heading", heading_level=1),
        },
    )
    output = result.format_for_display(show_headings=False)
    assert "Top Heading" not in output
    assert "Content." in output


def test_format_multiple_hits():
    result = SearchResult(
        block_id=3,
        block_text="ab cd ab",
        hits=[Hit(0, 2), Hit(6, 8)],
        heading_context={},
    )
    output = result.format_for_display()
    assert "0-2" in output
    assert "6-8" in output
