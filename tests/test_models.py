"""Tests for data models."""

from versiref.search.models import BlockInfo, SearchResult


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
        heading_context={},
    )
    output = result.format_for_display()
    assert "[Block 5]" in output
    assert "Some text with a reference." in output


def test_format_shows_heading_context():
    result = SearchResult(
        block_id=5,
        block_text="Content.",
        heading_context={
            1: BlockInfo(id=1, text="# Top Heading", heading_level=1),
            2: BlockInfo(id=3, text="## Sub Heading", heading_level=2),
        },
    )
    output = result.format_for_display(show_headings=True)
    # Headings are annotated with their block IDs, matching `toc` output.
    assert "# Top Heading {block=1}" in output
    assert "## Sub Heading {block=3}" in output
    assert "Content." in output


def test_format_suppresses_headings():
    result = SearchResult(
        block_id=5,
        block_text="Content.",
        heading_context={
            1: BlockInfo(id=1, text="# Top Heading", heading_level=1),
        },
    )
    output = result.format_for_display(show_headings=False)
    assert "Top Heading" not in output
    assert "{block=" not in output
    assert "Content." in output


def test_format_xml_wraps_headings_with_block_tags():
    result = SearchResult(
        block_id=5,
        block_text="Content.",
        heading_context={
            1: BlockInfo(id=1, text="# Top Heading", heading_level=1),
            2: BlockInfo(id=3, text="## Sub Heading", heading_level=2),
        },
    )
    output = result.format_xml(show_headings=True)
    # Each heading is wrapped in <block n="..."> just like the matched block.
    assert '<block n="1">\n# Top Heading\n</block>' in output
    assert '<block n="3">\n## Sub Heading\n</block>' in output
    assert '<block n="5">\nContent.\n</block>' in output


def test_format_xml_suppresses_headings():
    result = SearchResult(
        block_id=5,
        block_text="Content.",
        heading_context={
            1: BlockInfo(id=1, text="# Top Heading", heading_level=1),
        },
    )
    output = result.format_xml(show_headings=False)
    assert "Top Heading" not in output
    assert '<block n="1">' not in output
    assert '<block n="5">' in output
