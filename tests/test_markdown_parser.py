"""Tests for the Markdown parser."""

from versiref.search.markdown_parser import (
    _extract_block,
    extract_milestones,
    parse_markdown,
)
from versiref.search.models import RawMilestone


def test_empty_input():
    assert parse_markdown("") == []


def test_single_paragraph():
    blocks = parse_markdown("Simple paragraph text.")
    assert len(blocks) == 1
    assert blocks[0].heading_level is None
    assert "Simple paragraph text." in blocks[0].text


def test_heading_level_1():
    blocks = parse_markdown("# Title\n")
    assert len(blocks) == 1
    assert blocks[0].heading_level == 1
    assert blocks[0].text.startswith("# ")
    assert "Title" in blocks[0].text


def test_heading_level_2():
    blocks = parse_markdown("## Section\n")
    assert len(blocks) == 1
    assert blocks[0].heading_level == 2
    assert blocks[0].text.startswith("## ")


def test_heading_levels_1_through_3():
    blocks = parse_markdown("# H1\n\n## H2\n\n### H3\n")
    assert [b.heading_level for b in blocks] == [1, 2, 3]


def test_heading_then_paragraph():
    blocks = parse_markdown("# Title\n\nSome paragraph text.\n")
    assert len(blocks) == 2
    assert blocks[0].heading_level == 1
    assert blocks[1].heading_level is None


def test_multiple_paragraphs():
    md = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.\n"
    blocks = parse_markdown(md)
    assert len(blocks) == 3
    assert all(b.heading_level is None for b in blocks)


def test_block_ids_sequential():
    blocks = parse_markdown("# H\n\nParagraph.\n")
    assert blocks[0].id == 0
    assert blocks[1].id == 1


def test_italic_preserved():
    blocks = parse_markdown("Text with *italic* word.")
    assert "*italic*" in blocks[0].text


def test_bold_preserved():
    blocks = parse_markdown("Text with **bold** word.")
    assert "**bold**" in blocks[0].text


def test_blockquote():
    blocks = parse_markdown("> Quoted text here.\n")
    assert len(blocks) == 1
    assert blocks[0].heading_level is None
    assert "Quoted text here." in blocks[0].text
    assert blocks[0].text.startswith(">")


def test_unordered_list():
    # Loose list (blank lines between items) gives the items paragraph children
    blocks = parse_markdown("- Item one\n\n- Item two\n")
    assert len(blocks) == 1
    assert "Item one" in blocks[0].text
    assert "Item two" in blocks[0].text


def test_ordered_list():
    blocks = parse_markdown("1. First\n\n2. Second\n")
    assert len(blocks) == 1
    assert "First" in blocks[0].text
    assert "Second" in blocks[0].text


def test_tight_unordered_list():
    """Tight list items give block_text children and must still be indexed."""
    blocks = parse_markdown("- Item one\n- Item two\n")
    assert len(blocks) == 1
    assert "Item one" in blocks[0].text
    assert "Item two" in blocks[0].text


def test_tight_ordered_list():
    blocks = parse_markdown("1. First cites Lk 1:28.\n2. Second cites Rom 5:20.\n")
    assert len(blocks) == 1
    assert "Lk 1:28" in blocks[0].text
    assert "Rom 5:20" in blocks[0].text


def test_tight_list_surrounded_by_paragraphs():
    """A tight list is its own block and does not displace its neighbors."""
    blocks = parse_markdown("Before.\n\n- Item one\n- Item two\n\nAfter.\n")
    assert [b.text for b in blocks] == ["Before.", "- Item one\n- Item two", "After."]


def test_nested_tight_list():
    blocks = parse_markdown("- Outer\n  - Inner\n")
    assert len(blocks) == 1
    assert "Outer" in blocks[0].text
    assert "Inner" in blocks[0].text


def test_milestone_inside_tight_list_item():
    """A milestone in a tight list item survives with an offset into the item."""
    blocks = parse_markdown("1. Citing <!-- page: 7 --> John 1:14.\n")
    assert len(blocks) == 1
    assert blocks[0].text == "1. Citing John 1:14."
    assert blocks[0].milestones == [RawMilestone(type="page", value="7", offset=10)]
    assert blocks[0].text[10:].startswith("John")


def test_unhandled_token_with_inline_children_recovers_text():
    """An unanticipated token type yields its text rather than being dropped."""
    token = {"type": "future_block", "children": [{"type": "text", "raw": "Lk 1:28"}]}
    assert _extract_block(token, "") == ("Lk 1:28", None)


def test_unhandled_token_with_block_children_recovers_text():
    token = {
        "type": "future_container",
        "children": [
            {"type": "paragraph", "children": [{"type": "text", "raw": "One"}]},
            {"type": "paragraph", "children": [{"type": "text", "raw": "Two"}]},
        ],
    }
    assert _extract_block(token, "") == ("One\nTwo", None)


def test_unhandled_token_with_only_raw_recovers_text():
    assert _extract_block({"type": "future_raw", "raw": "Lk 1:28"}, "") == (
        "Lk 1:28",
        None,
    )


def test_textless_token_is_dropped_with_a_warning(caplog):
    assert _extract_block({"type": "future_empty"}, "") == (None, None)
    assert "future_empty" in caplog.text


def test_blank_line_token_is_dropped_silently(caplog):
    assert _extract_block({"type": "blank_line"}, "") == (None, None)
    assert caplog.text == ""


def test_bible_reference_text_preserved():
    """References in block text must survive parsing so the scanner can find them."""
    blocks = parse_markdown("See also Lk 1:28 for context.\n")
    assert "Lk 1:28" in blocks[0].text


def test_structure_of_minimal_md(minimal_md):
    """The fixture markdown produces the expected block structure."""
    blocks = parse_markdown(minimal_md.read_text(encoding="utf-8"))
    heading_levels = [b.heading_level for b in blocks]
    assert heading_levels == [1, None, 2, None, None]


# --- Milestones ---


def test_extract_milestones_inline_page():
    text, milestones = extract_milestones("Hannah prayed <!-- page: 204 --> and wept.")
    assert text == "Hannah prayed and wept."
    assert milestones == [RawMilestone(type="page", value="204", offset=14)]
    # The offset points into the stripped text
    assert text[milestones[0].offset :].startswith("and wept")


def test_extract_milestones_at_end_of_text():
    text, milestones = extract_milestones("A short paragraph. <!-- page: 12 -->")
    assert text == "A short paragraph."
    assert milestones[0].offset == len(text)


def test_extract_milestones_multiple():
    text, milestones = extract_milestones(
        "Start <!-- page: 1 --> middle <!-- scope: Jn 8:7 --> end."
    )
    assert text == "Start middle end."
    assert [m.type for m in milestones] == ["page", "scope"]
    assert [m.offset for m in milestones] == [6, 13]


def test_extract_milestones_marg():
    text, milestones = extract_milestones("Excerpt 667. <!-- marg: 667a --> More text.")
    assert text == "Excerpt 667. More text."
    assert milestones == [RawMilestone(type="marg", value="667a", offset=13)]


def test_extract_milestones_ignores_other_comments():
    text, milestones = extract_milestones("Keep <!-- note: this --> comment.")
    assert text == "Keep <!-- note: this --> comment."
    assert milestones == []


def test_standalone_milestone_attaches_to_next_block():
    blocks = parse_markdown("Para one.\n\n<!-- page: 53 -->\n\nPara two.\n")
    assert [b.text for b in blocks] == ["Para one.", "Para two."]
    assert blocks[0].milestones == []
    assert blocks[1].milestones == [RawMilestone(type="page", value="53", offset=0)]


def test_trailing_milestone_attaches_to_last_block():
    blocks = parse_markdown("Only paragraph.\n\n<!-- page: 99 -->\n")
    assert len(blocks) == 1
    assert blocks[0].milestones == [
        RawMilestone(type="page", value="99", offset=len("Only paragraph."))
    ]


def test_milestone_in_heading():
    blocks = parse_markdown("## On Jn 8:7 <!-- scope: Jn 8:7 -->\n")
    assert len(blocks) == 1
    assert blocks[0].text == "## On Jn 8:7"
    assert blocks[0].heading_level == 2
    assert blocks[0].milestones == [
        RawMilestone(type="scope", value="Jn 8:7", offset=len("## On Jn 8:7"))
    ]


def test_milestone_preserves_fts_phrase_continuity():
    """Stripping must rejoin the phrase around a mid-sentence page break."""
    blocks = parse_markdown("faithful <!-- page: 204 --> persistence\n")
    assert blocks[0].text == "faithful persistence"
