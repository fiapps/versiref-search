"""Data models for versiref-search."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AbbreviationAnalysis:
    """Analysis of book abbreviations found in input text.

    Attributes:
        unrecognized: Abbreviations found in the text that the configured
            style does not recognize, mapped to an example of usage.
        needed_sets: Standard book-name set identifiers that, applied in
            order, give the largest additional coverage of `unrecognized`
            at each step (greedy minimum cover).
        remaining: Subset of `unrecognized` not covered by any candidate
            set, mapped to an example of usage.

    """

    unrecognized: dict[str, str]
    needed_sets: list[str]
    remaining: dict[str, str]


@dataclass(frozen=True)
class VersificationScore:
    """Result of analyzing a text against a single versification.

    Attributes:
        name: The versification identifier (e.g., "eng", "lxx").
        valid: Number of references that are valid in this versification.
        total: Total number of references in the analyzed pool.

    """

    name: str
    valid: int
    total: int

    @property
    def score(self) -> float:
        """Fraction of references valid in this versification (0.0 if empty)."""
        if self.total == 0:
            return 0.0
        return self.valid / self.total


@dataclass(frozen=True)
class RawMilestone:
    """A milestone marker extracted from the Markdown source.

    Attributes:
        type: Milestone type ("page", "scope", or "marg")
        value: Milestone value (e.g., "204" for a page, "John 7:53-8:11" or
            "end" for a scope, "667" or "667a" for a marginal number)
        offset: Character offset in the block's *stripped* text where the
            marker fell

    """

    type: str
    value: str
    offset: int


@dataclass
class BlockInfo:
    """Information about a content block.

    Attributes:
        id: Content block ID
        text: Markdown text of the block
        heading_level: Heading level (1-6) or None for non-headings
        milestones: Milestone markers falling in this block — extracted from
            its source text when indexing, read back from the index when
            retrieving content

    """

    id: int
    text: str
    heading_level: int | None = None
    milestones: list[RawMilestone] = field(default_factory=list)


def insert_milestone_markers(text: str, milestones: list[RawMilestone]) -> str:
    """Put milestone markers back into block text at their recorded offsets.

    Indexing strips the markers from the stored text, so a block whose page
    changes partway through gives no sign of where the break falls. Restoring
    them in the same ``<!-- page: 204 -->`` form they were written in shows
    which part of the block belongs to which page, and keeps the text
    re-indexable.

    Offsets are relative to the stored text; ``text`` may additionally hold
    ``<mark>`` highlight tags, which are skipped when locating an offset so a
    marker still lands between the right two words.

    Args:
        text: Block text, possibly with ``<mark>`` tags inserted
        milestones: Milestones falling in this block

    Returns:
        The text with a marker comment at each milestone's position

    """
    if not milestones:
        return text

    # Positions in `text` of each character of the stored (unhighlighted) text.
    positions: list[int] = []
    i = 0
    while i < len(text):
        if text.startswith("<mark>", i):
            i += len("<mark>")
        elif text.startswith("</mark>", i):
            i += len("</mark>")
        else:
            positions.append(i)
            i += 1
    positions.append(len(text))

    for milestone in sorted(milestones, key=lambda m: m.offset, reverse=True):
        offset = min(max(milestone.offset, 0), len(positions) - 1)
        pos = positions[offset]
        # Keep the marker outside a highlighted span it would otherwise open in.
        while text[:pos].endswith("<mark>"):
            pos -= len("<mark>")

        marker = f"<!-- {milestone.type}: {milestone.value} -->"
        # Restore the spacing the marker had before it was stripped, judged
        # from the neighboring stored characters rather than the display text.
        prev_char = text[positions[offset - 1]] if offset > 0 else ""
        next_char = text[positions[offset]] if offset < len(positions) - 1 else ""
        if prev_char and not prev_char.isspace():
            marker = " " + marker
        if next_char and not next_char.isspace():
            marker = marker + " "

        text = text[:pos] + marker + text[pos:]

    return text


def _milestone_annotations(
    page: str | None,
    marg: str | None,
    page_end: str | None = None,
    marg_end: str | None = None,
) -> list[str]:
    """Build ``"key value"`` display annotations for the milestones in effect.

    A milestone recorded inside the block or span gives a range
    (``"pages 204-205"``) rather than a single value.
    """
    annotations = []
    if page is not None:
        annotations.append(f"pages {page}-{page_end}" if page_end else f"page {page}")
    if marg is not None:
        annotations.append(f"marg {marg}-{marg_end}" if marg_end else f"marg {marg}")
    return annotations


def _milestone_xml_attrs(
    page: str | None,
    marg: str | None,
    page_end: str | None = None,
    marg_end: str | None = None,
) -> str:
    """Build XML attributes for the milestones in effect (e.g. ``page="204"``)."""
    attrs = ""
    if page is not None:
        attrs += f' page="{page}"'
        if page_end:
            attrs += f' page_end="{page_end}"'
    if marg is not None:
        attrs += f' marg="{marg}"'
        if marg_end:
            attrs += f' marg_end="{marg_end}"'
    return attrs


@dataclass
class SearchResult:
    """Result of a search query.

    Attributes:
        block_id: ID of the content block containing hits
        block_text: Markdown text of the content block (may contain <mark> tags
            for string search highlights, and milestone marker comments where
            a page or marginal number changes mid-block)
        heading_context: Dictionary mapping heading levels to BlockInfo for context
        page: Page value in effect at the start of the block, or None if the
            database has no page milestone before it
        marg: Marginal-number value in effect at the start of the block, or
            None if the database has no marg milestone before it
        page_end: Last page value recorded inside the block, when the page
            changes partway through it; None otherwise
        marg_end: Last marginal number recorded inside the block, when it
            changes partway through it; None otherwise

    """

    block_id: int
    block_text: str
    heading_context: dict[int, BlockInfo]
    page: str | None = None
    marg: str | None = None
    page_end: str | None = None
    marg_end: str | None = None

    def format_for_display(self, show_headings: bool = True) -> str:
        """Format the search result for terminal display.

        Args:
            show_headings: Whether to include heading context

        Returns:
            Formatted string for display

        """
        lines = []

        # Add heading context if requested — annotate each with its block ID
        # using the same `{block=N}` form that `toc` produces.
        if show_headings and self.heading_context:
            for level in sorted(self.heading_context.keys()):
                heading = self.heading_context[level]
                lines.append(f"{heading.text.strip()} {{block={heading.id}}}")

        # Add separator before content
        if lines:
            lines.append("")

        # Add the content block with ID (and page/marg, if known)
        annotations = _milestone_annotations(
            self.page, self.marg, self.page_end, self.marg_end
        )
        suffix = f", {', '.join(annotations)}" if annotations else ""
        lines.append(f"[Block {self.block_id}{suffix}]")
        lines.append(self.block_text)

        return "\n".join(lines)

    def format_xml(self, show_headings: bool = True) -> str:
        """Format the search result as XML-delimited Markdown.

        Args:
            show_headings: Whether to include heading context

        Returns:
            XML-formatted string

        """
        lines = ["<result>"]

        # Heading context — wrap each in <block n="..."> to match `toc`.
        if show_headings and self.heading_context:
            for level in sorted(self.heading_context.keys()):
                heading = self.heading_context[level]
                lines.append(f'<block n="{heading.id}">')
                lines.append(heading.text.strip())
                lines.append("</block>")

        attrs = _milestone_xml_attrs(self.page, self.marg, self.page_end, self.marg_end)
        lines.append(f'<block n="{self.block_id}"{attrs}>')
        lines.append(self.block_text)
        lines.append("</block>")
        lines.append("</result>")

        return "\n".join(lines)


@dataclass
class ScopeResult:
    """Result of a commentary-scope search.

    Represents a span of blocks that comments on the queried passage. The
    opening block (usually a heading) is carried for display; the full span
    can be retrieved with ``show --start block_start --end block_end``.

    Attributes:
        block_start: First content ID of the commented span
        block_end: Last content ID of the commented span (inclusive)
        block_text: Markdown text of the span's opening block
        heading_context: Dictionary mapping heading levels to BlockInfo for context
        page: Page value in effect at the span's start, or None
        marg: Marginal-number value in effect at the span's start, or None
        page_end: Last page value recorded inside the span, when the page
            changes over its course; None otherwise
        marg_end: Last marginal number recorded inside the span, when it
            changes over its course; None otherwise

    """

    block_start: int
    block_end: int
    block_text: str
    heading_context: dict[int, BlockInfo]
    page: str | None = None
    marg: str | None = None
    page_end: str | None = None
    marg_end: str | None = None

    def format_for_display(self, show_headings: bool = True) -> str:
        """Format the scope result for terminal display.

        Args:
            show_headings: Whether to include heading context

        Returns:
            Formatted string for display

        """
        lines = []

        if show_headings and self.heading_context:
            for level in sorted(self.heading_context.keys()):
                heading = self.heading_context[level]
                lines.append(f"{heading.text.strip()} {{block={heading.id}}}")

        if lines:
            lines.append("")

        annotations = _milestone_annotations(
            self.page, self.marg, self.page_end, self.marg_end
        )
        suffix = f", {', '.join(annotations)}" if annotations else ""
        lines.append(f"[Blocks {self.block_start}-{self.block_end}{suffix}]")
        lines.append(self.block_text)

        return "\n".join(lines)

    def format_xml(self, show_headings: bool = True) -> str:
        """Format the scope result as XML-delimited Markdown.

        Args:
            show_headings: Whether to include heading context

        Returns:
            XML-formatted string

        """
        lines = ["<result>"]

        if show_headings and self.heading_context:
            for level in sorted(self.heading_context.keys()):
                heading = self.heading_context[level]
                lines.append(f'<block n="{heading.id}">')
                lines.append(heading.text.strip())
                lines.append("</block>")

        attrs = f'start="{self.block_start}" end="{self.block_end}"'
        attrs += _milestone_xml_attrs(
            self.page, self.marg, self.page_end, self.marg_end
        )
        lines.append(f"<scope {attrs}>")
        lines.append(self.block_text)
        lines.append("</scope>")
        lines.append("</result>")

        return "\n".join(lines)
