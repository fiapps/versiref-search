"""Data models for versiref-search."""

from dataclasses import dataclass


@dataclass
class BlockInfo:
    """Information about a content block.

    Attributes:
        id: Content block ID
        text: Markdown text of the block
        heading_level: Heading level (1-6) or None for non-headings

    """

    id: int
    text: str
    heading_level: int | None = None


@dataclass
class SearchResult:
    """Result of a search query.

    Attributes:
        block_id: ID of the content block containing hits
        block_text: Markdown text of the content block (may contain <mark> tags
            for string search highlights)
        heading_context: Dictionary mapping heading levels to BlockInfo for context

    """

    block_id: int
    block_text: str
    heading_context: dict[int, BlockInfo]

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

        # Add the content block with ID
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

        lines.append(f'<block n="{self.block_id}">')
        lines.append(self.block_text)
        lines.append("</block>")
        lines.append("</result>")

        return "\n".join(lines)
