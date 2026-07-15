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
        type: Milestone type ("page" or "scope")
        value: Milestone value (e.g., "204" for a page, "John 7:53-8:11" or
            "end" for a scope)
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
        milestones: Milestone markers extracted from this block's source text

    """

    id: int
    text: str
    heading_level: int | None = None
    milestones: list[RawMilestone] = field(default_factory=list)


@dataclass
class SearchResult:
    """Result of a search query.

    Attributes:
        block_id: ID of the content block containing hits
        block_text: Markdown text of the content block (may contain <mark> tags
            for string search highlights)
        heading_context: Dictionary mapping heading levels to BlockInfo for context
        page: Page value in effect at the block, or None if the database has
            no page milestone before it

    """

    block_id: int
    block_text: str
    heading_context: dict[int, BlockInfo]
    page: str | None = None

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

        # Add the content block with ID (and page, if known)
        if self.page is not None:
            lines.append(f"[Block {self.block_id}, page {self.page}]")
        else:
            lines.append(f"[Block {self.block_id}]")
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

        if self.page is not None:
            lines.append(f'<block n="{self.block_id}" page="{self.page}">')
        else:
            lines.append(f'<block n="{self.block_id}">')
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

    """

    block_start: int
    block_end: int
    block_text: str
    heading_context: dict[int, BlockInfo]
    page: str | None = None

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

        if self.page is not None:
            lines.append(
                f"[Blocks {self.block_start}-{self.block_end}, page {self.page}]"
            )
        else:
            lines.append(f"[Blocks {self.block_start}-{self.block_end}]")
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
        if self.page is not None:
            attrs += f' page="{self.page}"'
        lines.append(f"<scope {attrs}>")
        lines.append(self.block_text)
        lines.append("</scope>")
        lines.append("</result>")

        return "\n".join(lines)
