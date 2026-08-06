"""Tests for data models."""

from versiref.search.models import (
    BlockInfo,
    RawMilestone,
    ScopeResult,
    SearchResult,
    insert_milestone_markers,
)


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


# --- Milestone markers and ranges ---


def test_insert_milestone_markers_mid_block():
    text = "Ending one page and starting another."
    milestones = [RawMilestone(type="page", value="507", offset=21)]
    assert insert_milestone_markers(text, milestones) == (
        "Ending one page and s <!-- page: 507 --> tarting another."
    )


def test_insert_milestone_markers_at_word_boundary_keeps_spacing():
    text = "No sin found in you."
    milestones = [RawMilestone(type="page", value="507", offset=7)]
    assert insert_milestone_markers(text, milestones) == (
        "No sin <!-- page: 507 --> found in you."
    )


def test_insert_milestone_markers_at_block_start():
    text = "A new page opens here."
    milestones = [RawMilestone(type="page", value="507", offset=0)]
    assert insert_milestone_markers(text, milestones) == (
        "<!-- page: 507 --> A new page opens here."
    )


def test_insert_milestone_markers_several_in_order():
    text = "One two three"
    milestones = [
        RawMilestone(type="page", value="9", offset=4),
        RawMilestone(type="marg", value="42", offset=8),
    ]
    assert insert_milestone_markers(text, milestones) == (
        "One <!-- page: 9 --> two <!-- marg: 42 --> three"
    )


def test_insert_milestone_markers_skips_highlight_tags():
    # Offsets are relative to the unhighlighted text: 7 falls before "found".
    text = "No sin <mark>found in you</mark>."
    milestones = [RawMilestone(type="page", value="507", offset=7)]
    assert insert_milestone_markers(text, milestones) == (
        "No sin <!-- page: 507 --> <mark>found in you</mark>."
    )


def test_insert_milestone_markers_inside_highlight_span():
    text = "No <mark>sin found</mark> in you."
    milestones = [RawMilestone(type="page", value="507", offset=7)]
    assert insert_milestone_markers(text, milestones) == (
        "No <mark>sin <!-- page: 507 --> found</mark> in you."
    )


def test_insert_milestone_markers_no_milestones():
    assert insert_milestone_markers("Unchanged.", []) == "Unchanged."


def test_format_shows_page_range_when_page_changes_mid_block():
    result = SearchResult(
        block_id=5,
        block_text="Content.",
        heading_context={},
        page="1:506",
        page_end="1:507",
    )
    assert "[Block 5, pages 1:506-1:507]" in result.format_for_display()
    assert 'page="1:506" page_end="1:507"' in result.format_xml()


def test_format_shows_single_page_when_it_does_not_change():
    result = SearchResult(
        block_id=5, block_text="Content.", heading_context={}, page="204"
    )
    assert "[Block 5, page 204]" in result.format_for_display()
    assert "page_end" not in result.format_xml()


def test_format_shows_marg_range():
    result = SearchResult(
        block_id=5,
        block_text="Content.",
        heading_context={},
        marg="667",
        marg_end="668",
    )
    assert "[Block 5, marg 667-668]" in result.format_for_display()
    assert 'marg="667" marg_end="668"' in result.format_xml()


def test_scope_result_formats_page_range():
    result = ScopeResult(
        block_start=10,
        block_end=20,
        block_text="Opening block.",
        heading_context={},
        page="53",
        page_end="55",
    )
    assert "[Blocks 10-20, pages 53-55]" in result.format_for_display()
    assert 'page="53" page_end="55"' in result.format_xml()
