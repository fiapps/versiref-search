"""Search module for versiref-search."""

from pathlib import Path
from typing import Optional
from versiref import Versification, RefParser, RefStyle, standard_names

from .database import Database
from .models import SearchResult, Hit, BlockInfo


def search_database(
    db_path: str | Path,
    reference_query: Optional[str] = None,
    string_query: Optional[str] = None,
    include_headings: bool = True,
    ref_style: Optional[RefStyle] = None,
    name_sets: Optional[list[str]] = None,
) -> list[SearchResult]:
    """Search a database for Bible references and/or text strings.

    Args:
        db_path: Path to SQLite database file
        reference_query: Bible reference to search for (e.g., "Romans 3", "Isaiah 7:14")
        string_query: Text string to search for (case-insensitive)
        include_headings: Whether to include heading context in results
        ref_style: Optional RefStyle for parsing reference queries
        name_sets: List of book name set identifiers (ignored if ref_style provided)

    Returns:
        List of SearchResult objects in document order

    Raises:
        FileNotFoundError: If database doesn't exist
        ValueError: If neither reference_query nor string_query is provided,
            or if reference_query is invalid
    """
    if reference_query is None and string_query is None:
        raise ValueError("At least one of reference_query or string_query must be provided")

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        # Get versification from database metadata
        versification_name = db.get_metadata("versification_scheme")
        if not versification_name:
            raise ValueError("Database missing versification_scheme metadata")

        # Collect all hits by content_id
        hits_by_block: dict[int, list[Hit]] = {}

        # Search by reference if provided
        if reference_query:
            # Setup versiref parser
            versification = Versification.named(versification_name)

            # Build reference style
            if ref_style is None:
                if name_sets is None:
                    # Use same defaults as indexer
                    name_sets = ["en-sbl_abbreviations", "en-cmos_short", "en-sbl_names"]
                ref_style = RefStyle(names=standard_names(name_sets[0]))
                for name_set in name_sets[1:]:
                    ref_style.also_recognize(name_set)

            parser = RefParser(ref_style, versification)

            # Parse reference query
            try:
                ref = parser.parse(reference_query, silent=False)
            except Exception as e:
                raise ValueError(f"Invalid reference query '{reference_query}': {e}")

            if ref is None:
                raise ValueError(f"Could not parse reference query '{reference_query}'")

            # Search for each verse range in the reference
            for verse_start, verse_end in ref.range_keys():
                results = db.search_by_reference_range(verse_start, verse_end)
                for content_id, block_text, char_start, char_end in results:
                    if content_id not in hits_by_block:
                        hits_by_block[content_id] = []
                    # Add hit if not already present
                    hit = Hit(char_start, char_end)
                    if hit not in hits_by_block[content_id]:
                        hits_by_block[content_id].append(hit)

        # Search by string if provided
        if string_query:
            results = db.search_by_string(string_query)
            for content_id, block_text in results:
                if content_id not in hits_by_block:
                    hits_by_block[content_id] = []
                # Find all occurrences of the string in the block
                search_lower = string_query.lower()
                block_lower = block_text.lower()
                start = 0
                while True:
                    pos = block_lower.find(search_lower, start)
                    if pos == -1:
                        break
                    hit = Hit(pos, pos + len(string_query))
                    if hit not in hits_by_block[content_id]:
                        hits_by_block[content_id].append(hit)
                    start = pos + 1

        # Build SearchResult objects
        results = []
        for content_id in sorted(hits_by_block.keys()):
            # Get content block
            block_info = db.get_content_by_id(content_id)
            if not block_info:
                continue
            _, block_text, _ = block_info

            # Get heading context if requested
            heading_context = {}
            if include_headings:
                headings = db.get_all_preceding_headings(content_id)
                for level, (heading_id, heading_text) in headings.items():
                    heading_context[level] = BlockInfo(
                        id=heading_id,
                        text=heading_text,
                        heading_level=level
                    )

            # Sort hits by position
            hits = sorted(hits_by_block[content_id], key=lambda h: h.start_pos)

            results.append(SearchResult(
                block_id=content_id,
                block_text=block_text,
                hits=hits,
                heading_context=heading_context
            ))

        return results


def get_context(
    db_path: str | Path,
    start_id: int,
    end_id: int,
    include_headings: bool = True,
) -> list[BlockInfo]:
    """Get a range of content blocks with optional heading context.

    Args:
        db_path: Path to SQLite database file
        start_id: Starting content block ID (inclusive)
        end_id: Ending content block ID (inclusive)
        include_headings: Whether to include preceding headings before the range

    Returns:
        List of BlockInfo objects in document order

    Raises:
        FileNotFoundError: If database doesn't exist
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        blocks = []

        # Get heading context if requested
        if include_headings:
            headings = db.get_all_preceding_headings(start_id)
            for level in sorted(headings.keys()):
                heading_id, heading_text = headings[level]
                blocks.append(BlockInfo(
                    id=heading_id,
                    text=heading_text,
                    heading_level=level
                ))

        # Get content range
        content_blocks = db.get_content_range(start_id, end_id)
        for block_id, block_text, heading_level in content_blocks:
            blocks.append(BlockInfo(
                id=block_id,
                text=block_text,
                heading_level=heading_level
            ))

        return blocks
