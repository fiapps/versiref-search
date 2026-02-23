"""Markdown parsing for versiref-search."""

from typing import Any
import mistune
from .models import BlockInfo


def parse_markdown(markdown_text: str) -> list[BlockInfo]:
    """Parse Markdown text into block-level elements.

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

    # Walk the AST and extract block-level elements
    for token in tokens:
        block_text, heading_level = _extract_block(token, markdown_text)
        if block_text:
            blocks.append(
                BlockInfo(id=block_id, text=block_text, heading_level=heading_level)
            )
            block_id += 1

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

    # Paragraph
    elif token_type == "paragraph":
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
            if child.get("type") == "paragraph":
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
