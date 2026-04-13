"""Search module for versiref-search."""

from pathlib import Path
from versiref import Versification, RefParser, RefStyle

from .database import Database
from .models import SearchResult, BlockInfo


def _wrap_reference_spans(text: str, spans: set[tuple[int, int]]) -> str:
    """Wrap reference character ranges in ``<mark>…</mark>`` tags.

    Overlapping spans (e.g. a broad "Isa 7" containing a narrow "Isa 7:14")
    are collapsed to their outermost extent to avoid nested tags and to keep
    right-to-left insertion safe.
    """
    if not spans:
        return text

    ordered = sorted(spans)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if merged and start < merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (min(prev_start, start), max(prev_end, end))
        else:
            merged.append((start, end))

    for start, end in reversed(merged):
        text = text[:start] + "<mark>" + text[start:end] + "</mark>" + text[end:]
    return text


def search_database(
    db_path: str | Path,
    ref_style: RefStyle,
    reference_query: str | None = None,
    string_query: str | None = None,
    include_headings: bool = True,
    query_versification: str | None = None,
) -> list[SearchResult]:
    """Search a database for Bible references and/or text strings.

    Args:
        db_path: Path to SQLite database file
        ref_style: RefStyle for parsing reference queries
        reference_query: Bible reference to search for (e.g., "Romans 3", "Isaiah 7:14")
        string_query: Text string to search for (FTS5 word-boundary matching)
        include_headings: Whether to include heading context in results
        query_versification: Versification scheme of the query reference. When
            provided and different from the database's scheme, the parsed
            reference is mapped to the database's scheme via ``map_to()``.
            When ``None``, the database's own scheme is used to parse the query.

    Returns:
        List of SearchResult objects in document order

    Raises:
        FileNotFoundError: If database doesn't exist
        ValueError: If neither reference_query nor string_query is provided,
            or if reference_query is invalid, or if versification mapping fails

    """
    if reference_query is None and string_query is None:
        raise ValueError(
            "At least one of reference_query or string_query must be provided"
        )

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        # Get versification from database metadata
        versification_name = db.get_metadata("versification_scheme")
        if not versification_name:
            raise ValueError("Database missing versification_scheme metadata")

        # Collect matched blocks: content_id -> block_text
        # For string matches, block_text contains <mark> tags from FTS5 highlight().
        # For reference matches, we accumulate raw spans first and wrap them below.
        ref_raw: dict[int, tuple[str, set[tuple[int, int]]]] = {}
        ref_blocks: dict[int, str] = {}
        string_blocks: dict[int, str] = {}

        # Search by reference if provided
        if reference_query:
            db_versification = Versification.named(versification_name)

            if query_versification is not None:
                parse_versification = Versification.named(query_versification)
            else:
                parse_versification = db_versification

            parser = RefParser(ref_style, parse_versification)

            try:
                ref = parser.parse(reference_query, silent=False)
            except Exception as e:
                raise ValueError(f"Invalid reference query '{reference_query}': {e}")

            if ref is None:
                raise ValueError(f"Could not parse reference query '{reference_query}'")

            # Map to database versification if needed
            if (
                query_versification is not None
                and query_versification != versification_name
            ):
                mapped = ref.map_to(db_versification)
                if mapped is None:
                    raise ValueError(
                        f"Could not map reference '{reference_query}' "
                        f"from '{query_versification}' to '{versification_name}'"
                    )
                ref = mapped

            for verse_start, verse_end in ref.range_keys():
                ref_results = db.search_by_reference_range(verse_start, verse_end)
                for content_id, block_text, char_start, char_end in ref_results:
                    if content_id not in ref_raw:
                        ref_raw[content_id] = (block_text, set())
                    ref_raw[content_id][1].add((char_start, char_end))

            for content_id, (block_text, spans) in ref_raw.items():
                ref_blocks[content_id] = _wrap_reference_spans(block_text, spans)

        # Search by string if provided
        if string_query:
            string_results = db.search_by_string(string_query)
            for content_id, highlighted_text in string_results:
                if content_id not in string_blocks:
                    string_blocks[content_id] = highlighted_text

        # Merge: for blocks found by both queries, prefer the highlighted version
        all_block_ids = sorted(set(ref_blocks) | set(string_blocks))

        search_results: list[SearchResult] = []
        for content_id in all_block_ids:
            # Use highlighted text if available, otherwise plain text
            if content_id in string_blocks:
                block_text = string_blocks[content_id]
            else:
                block_text = ref_blocks[content_id]

            # Get heading context if requested
            heading_context: dict[int, BlockInfo] = {}
            if include_headings:
                headings = db.get_all_preceding_headings(content_id)
                for level, (heading_id, heading_text) in headings.items():
                    heading_context[level] = BlockInfo(
                        id=heading_id, text=heading_text, heading_level=level
                    )

            search_results.append(
                SearchResult(
                    block_id=content_id,
                    block_text=block_text,
                    heading_context=heading_context,
                )
            )

        return search_results


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
                blocks.append(
                    BlockInfo(id=heading_id, text=heading_text, heading_level=level)
                )

        # Get content range
        content_blocks = db.get_content_range(start_id, end_id)
        for block_id, block_text, heading_level in content_blocks:
            blocks.append(
                BlockInfo(id=block_id, text=block_text, heading_level=heading_level)
            )

        return blocks
