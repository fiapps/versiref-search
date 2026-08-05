"""Markdown parsing for versiref-search."""

import logging
import re
from typing import Any
import mistune
from .models import BlockInfo, RawMilestone

logger = logging.getLogger(__name__)

# Milestone markers: HTML comments of the form <!-- page: 204 -->,
# <!-- scope: John 7:53-8:11 -->, or <!-- marg: 667 -->. Other HTML comments
# are left untouched.
MILESTONE_RE = re.compile(r"<!--\s*(page|scope|marg)\s*:\s*(.*?)\s*-->")

# Block-level token types this module reconstructs explicitly. Used to tell a
# container of blocks from a container of inline elements when falling back on
# an unrecognized token.
BLOCK_TOKEN_TYPES = frozenset(
    {
        "heading",
        "paragraph",
        "block_text",
        "block_quote",
        "list",
        "list_item",
        "block_code",
        "thematic_break",
        "block_html",
    }
)

# Token types that carry no document text and are dropped without comment.
EMPTY_TOKEN_TYPES = frozenset({"blank_line", "linebreak", "softbreak"})


def extract_milestones(text: str) -> tuple[str, list[RawMilestone]]:
    """Extract milestone comments from block text and strip them.

    Each recognized milestone comment is removed from the text and recorded
    with its character offset in the *stripped* text. When removing an inline
    comment leaves a doubled space, one space is collapsed so the stored text
    reads naturally (and FTS phrase matching and reference scanning are not
    broken by the marker).

    Args:
        text: Block text possibly containing milestone comments

    Returns:
        Tuple of (stripped_text, milestones)

    """
    milestones: list[RawMilestone] = []
    parts: list[str] = []
    out_len = 0  # length of stripped text built so far
    pos = 0
    for match in MILESTONE_RE.finditer(text):
        before = text[pos : match.start()]
        pos = match.end()
        if before.endswith((" ", "\t")):
            if pos < len(text) and text[pos] in " \t":
                # Collapse "word <!--...--> word" to a single space between
                # words, skipping the space after the comment so the offset
                # points at the first character following the marker.
                pos += 1
            elif pos >= len(text) or text[pos] == "\n":
                # Drop the space left dangling before a comment that ends
                # the text or a line.
                before = before[:-1]
        parts.append(before)
        out_len += len(before)
        milestones.append(
            RawMilestone(type=match.group(1), value=match.group(2), offset=out_len)
        )
    parts.append(text[pos:])
    return "".join(parts), milestones


def parse_markdown(markdown_text: str) -> list[BlockInfo]:
    """Parse Markdown text into block-level elements.

    Milestone comments (``<!-- page: ... -->``, ``<!-- scope: ... -->``,
    ``<!-- marg: ... -->``) are stripped from block text and attached to the block as
    :class:`RawMilestone` entries. A block consisting only of milestone
    comments is dropped; its milestones attach to the next block at offset 0
    (or to the end of the last block if nothing follows).

    Args:
        markdown_text: Raw Markdown text to parse

    Returns:
        List of BlockInfo objects representing block-level elements in document order

    """
    # Create mistune markdown parser that returns AST
    markdown = mistune.create_markdown(renderer="ast")
    tokens: list[dict[str, Any]] = markdown(markdown_text)  # type: ignore[assignment]

    blocks = []
    block_id = 0  # We use 0-based IDs here; database will assign real IDs
    pending: list[RawMilestone] = []  # milestones awaiting their host block

    # Walk the AST and extract block-level elements
    for token in tokens:
        block_text, heading_level = _extract_block(token, markdown_text)
        if not block_text:
            continue
        stripped, milestones = extract_milestones(block_text)
        if not stripped.strip():
            # Block was only milestone comments; attach them to the next block.
            pending.extend(
                RawMilestone(type=m.type, value=m.value, offset=0) for m in milestones
            )
            continue
        if pending:
            milestones = pending + milestones
            pending = []
        blocks.append(
            BlockInfo(
                id=block_id,
                text=stripped,
                heading_level=heading_level,
                milestones=milestones,
            )
        )
        block_id += 1

    # Trailing milestones with no following block: attach to the last block
    # at its end.
    if pending and blocks:
        last = blocks[-1]
        last.milestones.extend(
            RawMilestone(type=m.type, value=m.value, offset=len(last.text))
            for m in pending
        )

    return blocks


def _extract_block(
    token: dict[str, Any], source_text: str
) -> tuple[str | None, int | None]:
    """Extract text and heading level from a token.

    Args:
        token: Mistune AST token
        source_text: Original Markdown source text

    Returns:
        Tuple of (block_text, heading_level) or (None, None) if not a block element

    """
    token_type = token.get("type")

    # Heading
    if token_type == "heading":
        level = token.get("attrs", {}).get("level")
        text = _extract_inline_text(token.get("children", []))
        if text:
            # Reconstruct heading with proper Markdown syntax
            heading_text = f"{'#' * level} {text}"
            return heading_text, level

    # Paragraph. ``block_text`` is what mistune gives a tight list item's
    # content in place of a paragraph; it holds the same inline children.
    elif token_type in ("paragraph", "block_text"):
        text = _extract_inline_text(token.get("children", []))
        if text:
            return text, None

    # Block quote
    elif token_type == "block_quote":
        lines: list[str] = []
        for child in token.get("children", []):
            child_text, _ = _extract_block(child, source_text)
            if child_text:
                # Add '> ' prefix to each line
                lines.extend(f"> {line}" for line in child_text.split("\n"))
        if lines:
            return "\n".join(lines), None

    # List (ordered or unordered)
    elif token_type in ("list", "list_item"):
        text = _extract_list_text(token)
        if text:
            return text, None

    # Code block
    elif token_type == "block_code":
        code = token.get("raw", "")
        info = token.get("attrs", {}).get("info", "")
        if info:
            return f"```{info}\n{code}\n```", None
        else:
            return f"```\n{code}\n```", None

    # Thematic break (horizontal rule)
    elif token_type == "thematic_break":
        return "---", None

    # Block HTML
    elif token_type == "block_html":
        return token.get("raw", ""), None

    # Anything else: recover the text rather than dropping it, so an
    # unanticipated token type costs formatting fidelity but never content.
    else:
        children = token.get("children") or []
        if any(child.get("type") in BLOCK_TOKEN_TYPES for child in children):
            parts = []
            for child in children:
                child_text, _ = _extract_block(child, source_text)
                if child_text:
                    parts.append(child_text)
            if parts:
                return "\n".join(parts), None
        elif children:
            text = _extract_inline_text(children)
            if text:
                return text, None
        elif token.get("raw"):
            return token["raw"], None
        if token_type not in EMPTY_TOKEN_TYPES:
            logger.warning(
                "Skipping Markdown token of unhandled type '%s'; "
                "any text it contained is not indexed.",
                token_type,
            )

    return None, None


def _extract_inline_text(children: list[dict[str, Any]]) -> str:
    """Extract text from inline elements (recursively).

    Args:
        children: List of inline token children

    Returns:
        Concatenated text from all inline elements

    """
    parts = []
    for child in children:
        child_type = child.get("type")

        if child_type == "text":
            parts.append(child.get("raw", ""))

        elif child_type == "emphasis":
            # Italic text
            inner = _extract_inline_text(child.get("children", []))
            parts.append(f"*{inner}*")

        elif child_type == "strong":
            # Bold text
            inner = _extract_inline_text(child.get("children", []))
            parts.append(f"**{inner}**")

        elif child_type == "codespan":
            # Inline code
            parts.append(f"`{child.get('raw', '')}`")

        elif child_type == "link":
            # Link
            inner = _extract_inline_text(child.get("children", []))
            url = child.get("attrs", {}).get("url", "")
            parts.append(f"[{inner}]({url})")

        elif child_type == "image":
            # Image
            alt = child.get("attrs", {}).get("alt", "")
            url = child.get("attrs", {}).get("url", "")
            parts.append(f"![{alt}]({url})")

        elif child_type == "linebreak":
            parts.append("\n")

        elif child_type == "softbreak":
            parts.append(" ")

        elif child_type == "inline_html":
            parts.append(child.get("raw", ""))

        else:
            # For any other inline type, try to extract children
            if "children" in child:
                parts.append(_extract_inline_text(child.get("children", [])))
            elif "raw" in child:
                parts.append(child.get("raw", ""))

    return "".join(parts)


def _extract_list_text(token: dict[str, Any]) -> str:
    """Extract text from list tokens.

    Args:
        token: List or list_item token

    Returns:
        Formatted list text

    """
    token_type = token.get("type")

    if token_type == "list":
        ordered = token.get("attrs", {}).get("ordered", False)
        items = []
        for i, child in enumerate(token.get("children", []), start=1):
            item_text = _extract_list_text(child)
            if item_text:
                if ordered:
                    items.append(f"{i}. {item_text}")
                else:
                    items.append(f"- {item_text}")
        return "\n".join(items)

    elif token_type == "list_item":
        parts = []
        for child in token.get("children", []):
            if child.get("type") in ("paragraph", "block_text"):
                text = _extract_inline_text(child.get("children", []))
                if text:
                    parts.append(text)
            elif child.get("type") == "list":
                # Nested list
                nested = _extract_list_text(child)
                if nested:
                    # Indent nested list items
                    indented = "\n".join(f"  {line}" for line in nested.split("\n"))
                    parts.append(indented)
            else:
                other_text, _ = _extract_block(child, "")
                if other_text:
                    parts.append(other_text)
        return "\n".join(parts)

    return ""
