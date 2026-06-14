"""Search module for versiref-search."""

from pathlib import Path
from versiref import Versification, RefParser, RefStyle

from .database import Database
from .models import SearchResult, BlockInfo

DEFAULT_MAX_SECTION_BLOCKS = 200


class SectionTooLargeError(Exception):
    """Raised when a requested section exceeds the maximum block count.

    Carries the actual ``block_count`` and the ``max_blocks`` limit so callers
    can craft an actionable message.
    """

    def __init__(self, block_count: int, max_blocks: int):
        """Record the offending block count and the limit it exceeded."""
        self.block_count = block_count
        self.max_blocks = max_blocks
        super().__init__(f"section has {block_count} blocks (max {max_blocks})")


class AmbiguousSectionError(Exception):
    """Raised when a heading-text query matches more than one section.

    Carries the matching headings as ``candidates`` (a list of BlockInfo) so
    callers can list them for disambiguation.
    """

    def __init__(self, candidates: list[BlockInfo]):
        """Record the matching headings for the caller to disambiguate."""
        self.candidates = candidates
        super().__init__(f"{len(candidates)} headings match the query")


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
    start_id: int | None = None,
    end_id: int | None = None,
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
        start_id: Optional minimum content block ID (inclusive). Limits the
            range of blocks that will be searched.
        end_id: Optional maximum content block ID (inclusive). Limits the
            range of blocks that will be searched.

    Returns:
        List of SearchResult objects in document order

    Raises:
        FileNotFoundError: If database doesn't exist
        IncompatibleDatabaseError: If the database is not a compatible
            versiref-search index
        ValueError: If neither reference_query nor string_query is provided,
            or if reference_query is invalid, or if versification mapping fails,
            or if start_id > end_id

    """
    if reference_query is None and string_query is None:
        raise ValueError(
            "At least one of reference_query or string_query must be provided"
        )

    if start_id is not None and end_id is not None and start_id > end_id:
        raise ValueError(f"start_id ({start_id}) must not exceed end_id ({end_id})")

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        db.validate_schema()

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
                ref_results = db.search_by_reference_range(
                    verse_start,
                    verse_end,
                    block_start=start_id,
                    block_end=end_id,
                )
                for content_id, block_text, char_start, char_end in ref_results:
                    if content_id not in ref_raw:
                        ref_raw[content_id] = (block_text, set())
                    ref_raw[content_id][1].add((char_start, char_end))

            for content_id, (block_text, spans) in ref_raw.items():
                ref_blocks[content_id] = _wrap_reference_spans(block_text, spans)

        # Search by string if provided
        if string_query:
            string_results = db.search_by_string(
                string_query, block_start=start_id, block_end=end_id
            )
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


def get_toc(
    db_path: str | Path,
    depth: int = 2,
    start_id: int | None = None,
    end_id: int | None = None,
) -> list[BlockInfo]:
    """Get a table of contents (heading blocks) from a database.

    Args:
        db_path: Path to SQLite database file
        depth: Maximum heading level to include (1-6). Defaults to 2.
        start_id: Optional minimum content block ID (inclusive)
        end_id: Optional maximum content block ID (inclusive)

    Returns:
        List of BlockInfo objects for heading blocks in document order

    Raises:
        FileNotFoundError: If database doesn't exist
        IncompatibleDatabaseError: If the database is not a compatible
            versiref-search index
        ValueError: If depth is not between 1 and 6, or if start_id > end_id

    """
    if depth < 1 or depth > 6:
        raise ValueError(f"depth must be between 1 and 6 (got {depth})")
    if start_id is not None and end_id is not None and start_id > end_id:
        raise ValueError(f"start_id ({start_id}) must not exceed end_id ({end_id})")

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        db.validate_schema()
        rows = db.get_headings(max_level=depth, block_start=start_id, block_end=end_id)
        return [
            BlockInfo(id=block_id, text=text, heading_level=level)
            for block_id, text, level in rows
        ]


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
        IncompatibleDatabaseError: If the database is not a compatible
            versiref-search index

    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        db.validate_schema()
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


def _collect_section(
    db: Database,
    section_start_id: int,
    end_anchor_id: int,
    level: int,
    include_headings: bool,
    max_blocks: int,
) -> list[BlockInfo]:
    """Assemble the blocks of a section between two heading boundaries.

    The section runs from ``section_start_id`` (the opening heading, inclusive)
    up to but excluding the next heading at level <= ``level`` that follows
    ``end_anchor_id``. ``end_anchor_id`` equals ``section_start_id`` for a
    single section, or a later block when expanding to span several.

    Raises:
        SectionTooLargeError: If the section spans more than ``max_blocks``.

    """
    next_id = db.get_next_heading_id(end_anchor_id, level)
    if next_id is not None:
        last_id = next_id - 1
    else:
        max_id = db.get_max_content_id()
        if max_id is None:
            return []
        last_id = max_id

    count = db.count_content_range(section_start_id, last_id)
    if count > max_blocks:
        raise SectionTooLargeError(count, max_blocks)

    blocks: list[BlockInfo] = []

    # Optionally prepend the ancestor headings above the section (the section's
    # own heading is the first block of the range, so only shallower levels).
    if include_headings:
        ancestors = db.get_all_preceding_headings(section_start_id)
        for lvl in sorted(ancestors):
            if lvl < level:
                heading_id, heading_text = ancestors[lvl]
                blocks.append(
                    BlockInfo(id=heading_id, text=heading_text, heading_level=lvl)
                )

    for block_id, block_text, heading_level in db.get_content_range(
        section_start_id, last_id
    ):
        blocks.append(
            BlockInfo(id=block_id, text=block_text, heading_level=heading_level)
        )

    return blocks


def get_section_by_block(
    db_path: str | Path,
    block_id: int,
    level: int,
    end_id: int | None = None,
    include_headings: bool = False,
    max_blocks: int = DEFAULT_MAX_SECTION_BLOCKS,
) -> list[BlockInfo]:
    """Get the whole section, at a heading level, containing a block.

    Finds the nearest heading at ``level`` at or before ``block_id`` (the
    section's opening heading) and returns every block from it up to but
    excluding the next heading at level <= ``level``. When ``end_id`` is given
    and lies in a later section, the result expands to span through that
    section too.

    Args:
        db_path: Path to SQLite database file
        block_id: Block whose enclosing section is wanted (range start)
        level: Heading level (1-6) that defines section boundaries
        end_id: Optional block ID extending the range; the section(s) covering
            ``block_id`` through ``end_id`` are returned. Defaults to block_id.
        include_headings: Whether to prepend the ancestor headings above the
            section
        max_blocks: Maximum number of blocks before refusing

    Returns:
        List of BlockInfo objects in document order

    Raises:
        FileNotFoundError: If database doesn't exist
        IncompatibleDatabaseError: If the database is not a compatible
            versiref-search index
        ValueError: If level is not between 1 and 6, end_id < block_id, or the
            block is not inside a section at the requested level
        SectionTooLargeError: If the section spans more than max_blocks

    """
    if level < 1 or level > 6:
        raise ValueError(f"level must be between 1 and 6 (got {level})")

    if end_id is None:
        end_id = block_id
    if end_id < block_id:
        raise ValueError(
            f"end_id ({end_id}) must not be less than block_id ({block_id})"
        )

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        db.validate_schema()

        enclosing = db.get_enclosing_heading(block_id, level)
        if enclosing is None:
            raise ValueError(
                f"No heading at level {level} or above precedes block {block_id}"
            )
        section_start_id, _, enclosing_level = enclosing
        if enclosing_level != level:
            raise ValueError(
                f"Block {block_id} is not within a level-{level} section "
                f"(nearest enclosing heading is level {enclosing_level} "
                f"at block {section_start_id})"
            )

        return _collect_section(
            db, section_start_id, end_id, level, include_headings, max_blocks
        )


def get_section_by_heading(
    db_path: str | Path,
    heading_text: str,
    level: int,
    include_headings: bool = False,
    max_blocks: int = DEFAULT_MAX_SECTION_BLOCKS,
) -> list[BlockInfo]:
    """Get the whole section whose heading text matches a query.

    Matches headings at ``level`` whose text contains ``heading_text``
    (case-insensitive). The matched heading and every following block up to
    but excluding the next heading at level <= ``level`` are returned.

    Args:
        db_path: Path to SQLite database file
        heading_text: Substring to match against level-``level`` headings
        level: Heading level (1-6) that defines section boundaries
        include_headings: Whether to prepend the ancestor headings above the
            section
        max_blocks: Maximum number of blocks before refusing

    Returns:
        List of BlockInfo objects in document order

    Raises:
        FileNotFoundError: If database doesn't exist
        IncompatibleDatabaseError: If the database is not a compatible
            versiref-search index
        ValueError: If level is not between 1 and 6, or no heading matches
        AmbiguousSectionError: If more than one heading matches
        SectionTooLargeError: If the section spans more than max_blocks

    """
    if level < 1 or level > 6:
        raise ValueError(f"level must be between 1 and 6 (got {level})")

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        db.validate_schema()

        matches = db.find_headings_by_text(heading_text, level)
        if not matches:
            raise ValueError(f"No level-{level} heading matches {heading_text!r}")
        if len(matches) > 1:
            raise AmbiguousSectionError(
                [
                    BlockInfo(id=mid, text=mtext, heading_level=level)
                    for mid, mtext in matches
                ]
            )

        section_start_id = matches[0][0]
        return _collect_section(
            db, section_start_id, section_start_id, level, include_headings, max_blocks
        )
