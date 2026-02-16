"""Data models for versiref-search."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Hit:
    """Represents a single hit within a content block.

    Attributes:
        start_pos: Character position where the hit starts
        end_pos: Character position where the hit ends
    """

    start_pos: int
    end_pos: int


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
    heading_level: Optional[int] = None


@dataclass
class SearchResult:
    """Result of a search query.

    Attributes:
        block_id: ID of the content block containing hits
        block_text: Markdown text of the content block
        hits: List of hit positions within the block
        heading_context: Dictionary mapping heading levels to BlockInfo for context
    """

    block_id: int
    block_text: str
    hits: list[Hit]
    heading_context: dict[int, BlockInfo]

    def format_for_display(self, show_headings: bool = True) -> str:
        """Format the search result for terminal display.

        Args:
            show_headings: Whether to include heading context

        Returns:
            Formatted string for display
        """
        lines = []

        # Add heading context if requested
        if show_headings and self.heading_context:
            for level in sorted(self.heading_context.keys()):
                heading = self.heading_context[level]
                indent = "  " * (level - 1)
                lines.append(f"{indent}{heading.text.strip()}")

        # Add separator before content
        if lines:
            lines.append("")

        # Add the content block with ID
        lines.append(f"[Block {self.block_id}]")
        lines.append(self.block_text)

        # Add hit positions info
        if self.hits:
            hit_positions = ", ".join(
                f"{hit.start_pos}-{hit.end_pos}" for hit in self.hits
            )
            lines.append(f"  (Hits at: {hit_positions})")

        return "\n".join(lines)
