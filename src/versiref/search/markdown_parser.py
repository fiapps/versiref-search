"""Markdown parsing for versiref-search."""

import datetime
import difflib
import logging
import re
from typing import Any
import mistune
import yaml
from .models import BlockInfo, RawMilestone

logger = logging.getLogger(__name__)

# Milestone markers: HTML comments of the form <!-- page: 204 -->,
# <!-- scope: John 7:53-8:11 -->, <!-- marg: 667 -->, or
# <!-- date: 1896-09-20 -->. The type may be in any letter case. Other HTML
# comments are left untouched.
MILESTONE_TYPES = ("page", "scope", "marg", "date")
MILESTONE_RE = re.compile(
    rf"<!--\s*({'|'.join(MILESTONE_TYPES)})\s*:\s*(.*?)\s*-->", re.IGNORECASE
)

# Any comment with the "type: value" shape of a milestone. Most are nothing of
# the kind (<!-- TODO: ... -->, <!-- note: ... -->); see find_misspelled_milestones.
_TYPED_COMMENT_RE = re.compile(r"<!--\s*([A-Za-z]+)\s*:.*?-->")

# How closely a comment's type must resemble a milestone type to be reported
# as a likely misspelling: close enough to catch a transposition ("pgae"), a
# dropped letter ("pag"), or a plural ("pages"), but not an unrelated word
# that shares a couple of letters ("date", "note", "image").
_MISSPELLING_CUTOFF = 0.7

# YAML frontmatter: a "---" fence on the very first line, closed by a line of
# "---" or "...". Markdown itself has no notion of frontmatter, so left in
# place the opening fence parses as a thematic break and the closing one as a
# setext underline, turning the whole block into a heading.
FRONTMATTER_OPEN_RE = re.compile(r"^---[ \t]*\r?\n")
FRONTMATTER_CLOSE_RE = re.compile(r"^(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.MULTILINE)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a leading YAML frontmatter block off Markdown text.

    Recognized only at the very start of the document. Anything that does not
    parse as a YAML mapping is left alone and reported, on the assumption that
    a leading ``---`` was meant as a thematic break.

    Args:
        text: Raw Markdown text, possibly opening with frontmatter

    Returns:
        Tuple of (frontmatter, body). The frontmatter is empty when there is
        none, in which case the body is the text unchanged.

    """
    opening = FRONTMATTER_OPEN_RE.match(text)
    if opening is None:
        return {}, text
    closing = FRONTMATTER_CLOSE_RE.search(text, opening.end())
    if closing is None:
        return {}, text
    try:
        data = yaml.safe_load(text[opening.end() : closing.start()])
    except yaml.YAMLError as e:
        logger.warning(
            "Leading '---' block is not valid YAML (%s); "
            "treating it as Markdown rather than frontmatter.",
            e,
        )
        return {}, text
    if data is None:
        data = {}  # empty frontmatter, still worth stripping
    if not isinstance(data, dict):
        logger.warning(
            "Leading '---' block is YAML but not a mapping; "
            "treating it as Markdown rather than frontmatter."
        )
        return {}, text
    return data, text[closing.end() :]


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


def find_misspelled_milestones(text: str) -> list[tuple[str, str]]:
    """Find comments that look like milestones with a misspelled type.

    A comment such as ``<!-- pgae: 204 -->`` is not a milestone, so it stays
    in the text and records nothing, which is almost never what its author
    meant. Only types resembling a real one are reported: an unrelated
    ``<!-- TODO: ... -->`` or ``<!-- note: ... -->`` is left alone.

    Args:
        text: Block text from which recognized milestones have been stripped

    Returns:
        List of (comment, intended type) pairs, in order of appearance

    """
    suspects: list[tuple[str, str]] = []
    for match in _TYPED_COMMENT_RE.finditer(text):
        close = difflib.get_close_matches(
            match.group(1).lower(), MILESTONE_TYPES, n=1, cutoff=_MISSPELLING_CUTOFF
        )
        if close:
            suspects.append((match.group(0), close[0]))
    return suspects


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
            RawMilestone(
                type=match.group(1).lower(), value=match.group(2), offset=out_len
            )
        )
    parts.append(text[pos:])
    return "".join(parts), milestones


def _frontmatter_date(frontmatter: dict[str, Any]) -> str | None:
    """Take the document's date from its frontmatter, as milestone text.

    YAML reads an ISO 8601 date as a date object, which is written back out
    in ISO form; anything else is kept as written.
    """
    value = frontmatter.get("date")
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value).strip() or None
    if value is not None:
        logger.warning("Frontmatter date %r is not a date; ignoring it.", value)
    return None


def _normalize_heading_text(text: str) -> str:
    """Reduce heading or title text for comparison."""
    return " ".join(text.lstrip("#").split()).casefold()


def _title_block(
    frontmatter: dict[str, Any], level: int, blocks: list[BlockInfo]
) -> BlockInfo | None:
    """Build a heading block from the frontmatter title, if one is warranted.

    Returns None when the document already heads itself: either it carries a
    heading at ``level`` or shallower — adding another would give it two
    competing top-level headings — or its first heading repeats the title,
    which would index the title twice. Both are common in corpora whose
    documents are converted from a source that already had a title.
    """
    title = frontmatter.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    headings = [b for b in blocks if b.heading_level is not None]
    if any(b.heading_level is not None and b.heading_level <= level for b in headings):
        return None
    if headings and _normalize_heading_text(headings[0].text) == (
        _normalize_heading_text(title)
    ):
        return None
    return BlockInfo(
        id=0,
        text=f"{'#' * level} {title.strip()}",
        heading_level=level,
        milestones=[],
    )


def parse_markdown(
    markdown_text: str,
    *,
    frontmatter: dict[str, Any] | None = None,
    frontmatter_title_level: int | None = 1,
) -> list[BlockInfo]:
    """Parse Markdown text into block-level elements.

    A leading YAML frontmatter block is stripped and not indexed. When it
    declares a ``date``, the document's first block carries it as a date
    milestone. When it declares a ``title``, a heading carrying that title opens the document, so
    that blocks before its first real heading still have heading context —
    unless the document already heads itself (see :func:`_title_block`).

    Milestone comments (``<!-- page: ... -->``, ``<!-- scope: ... -->``,
    ``<!-- marg: ... -->``, ``<!-- date: ... -->``) are stripped from block text and attached to the block as
    :class:`RawMilestone` entries. A comment whose type looks like a
    misspelling of one of these is left in the text and reported as a warning. A block consisting only of milestone
    comments is dropped; its milestones attach to the next block at offset 0
    (or to the end of the last block if nothing follows).

    Args:
        markdown_text: Raw Markdown text to parse
        frontmatter: Frontmatter already split off ``markdown_text`` by the
            caller, which is then taken to hold the body alone. Pass it to
            avoid splitting the document twice, which would repeat any
            warning about a malformed frontmatter block.
        frontmatter_title_level: Heading level for the title taken from
            frontmatter, or None to index no title heading

    Returns:
        List of BlockInfo objects representing block-level elements in document order

    """
    if frontmatter is None:
        frontmatter, markdown_text = split_frontmatter(markdown_text)

    # Create mistune markdown parser that returns AST
    markdown = mistune.create_markdown(renderer="ast")
    tokens: list[dict[str, Any]] = markdown(markdown_text)  # type: ignore[assignment]

    blocks = []
    block_id = 0  # We use 0-based IDs here; database will assign real IDs
    pending: list[RawMilestone] = []  # milestones awaiting their host block
    # Comments that look like misspelled milestones, keyed by the type as
    # written: (first such comment, intended type, number seen).
    misspelled: dict[str, tuple[str, str, int]] = {}

    # Walk the AST and extract block-level elements
    for token in tokens:
        block_text, heading_level = _extract_block(token, markdown_text)
        if not block_text:
            continue
        stripped, milestones = extract_milestones(block_text)
        for comment, intended in find_misspelled_milestones(stripped):
            written = comment[4:].split(":", 1)[0].strip()
            first, _, seen = misspelled.get(written, (comment, intended, 0))
            misspelled[written] = (first, intended, seen + 1)
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

    for first, intended, seen in misspelled.values():
        logger.warning(
            'Comment "%s" looks like a misspelled "%s" milestone%s; '
            "it is indexed as text and records no milestone.",
            first.strip(),
            intended,
            f" ({seen} like it)" if seen > 1 else "",
        )

    if frontmatter_title_level is not None:
        title = _title_block(frontmatter, frontmatter_title_level, blocks)
        if title is not None:
            blocks.insert(0, title)
            for position, block in enumerate(blocks):
                block.id = position

    # The frontmatter date dates the document from its first block on, unless
    # the document opens with a date marker of its own.
    date = _frontmatter_date(frontmatter)
    if date is not None and blocks:
        opening = blocks[0].milestones
        if not any(m.type == "date" and m.offset == 0 for m in opening):
            opening.insert(0, RawMilestone(type="date", value=date, offset=0))

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
        children = token.get("children", [])
        # A table reaches us as a paragraph of rows. Its line breaks are its
        # structure, so keep them rather than joining the rows into one line.
        text = _extract_inline_text(children, softbreak="\n")
        if not _is_table(text):
            text = _extract_inline_text(children)
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


# The delimiter row under a table's header: "|---|:--:|" and the like.
_TABLE_DELIMITER_RE = re.compile(r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*")


def _is_table(text: str) -> bool:
    """Tell whether paragraph text, with its line breaks kept, is a pipe table."""
    lines = text.split("\n")
    return (
        len(lines) >= 2
        and "|" in lines[0]
        and "|" in lines[1]
        and _TABLE_DELIMITER_RE.fullmatch(lines[1]) is not None
    )


def _extract_inline_text(children: list[dict[str, Any]], softbreak: str = " ") -> str:
    """Extract text from inline elements (recursively).

    Args:
        children: List of inline token children
        softbreak: What a line break within a paragraph becomes

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
            inner = _extract_inline_text(child.get("children", []), softbreak)
            parts.append(f"*{inner}*")

        elif child_type == "strong":
            # Bold text
            inner = _extract_inline_text(child.get("children", []), softbreak)
            parts.append(f"**{inner}**")

        elif child_type == "codespan":
            # Inline code
            parts.append(f"`{child.get('raw', '')}`")

        elif child_type == "link":
            # Link
            inner = _extract_inline_text(child.get("children", []), softbreak)
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
            parts.append(softbreak)

        elif child_type == "inline_html":
            parts.append(child.get("raw", ""))

        else:
            # For any other inline type, try to extract children
            if "children" in child:
                parts.append(_extract_inline_text(child.get("children", []), softbreak))
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
        attrs = token.get("attrs", {})
        ordered = attrs.get("ordered", False)
        # Number from where the source did: "42." opening a numbered paragraph
        # is that paragraph's citation handle, not an arbitrary list ordinal.
        start = attrs.get("start")
        first = start if isinstance(start, int) else 1
        items = []
        for i, child in enumerate(token.get("children", []), start=first):
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
