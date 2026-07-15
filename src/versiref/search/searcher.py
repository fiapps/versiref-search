"""Search module for versiref-search."""

import re
from pathlib import Path
from typing import Any
from versiref import Versification, RefParser, RefStyle

from .database import Database
from .models import ScopeResult, SearchResult, BlockInfo

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


def _parse_query_reference(
    ref_style: RefStyle,
    reference_query: str,
    versification_name: str,
    query_versification: str | None,
) -> Any:
    """Parse a reference query and map it into a database's versification.

    Args:
        ref_style: RefStyle for parsing the query
        reference_query: The reference string to parse
        versification_name: The database's versification scheme
        query_versification: Scheme the query is written in, or None to use
            the database's own scheme

    Returns:
        The parsed reference, mapped into the database's versification.

    Raises:
        ValueError: If the query cannot be parsed or mapped.

    """
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
    if query_versification is not None and query_versification != versification_name:
        mapped = ref.map_to(db_versification)
        if mapped is None:
            raise ValueError(
                f"Could not map reference '{reference_query}' "
                f"from '{query_versification}' to '{versification_name}'"
            )
        ref = mapped

    return ref


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
            ref = _parse_query_reference(
                ref_style, reference_query, versification_name, query_versification
            )

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
                    page=db.get_page_for_block(content_id),
                )
            )

        return search_results


def search_commentary(
    db_path: str | Path,
    ref_style: RefStyle,
    reference_query: str,
    include_headings: bool = True,
    query_versification: str | None = None,
) -> list[ScopeResult]:
    """Search a database for commentary on a passage.

    Matches commentary scopes (sections recorded as commenting on a passage,
    as opposed to merely citing it) whose verse range overlaps the query.
    When matching scopes nest, only the narrowest are returned: a scope whose
    block range strictly contains another matching scope is dropped, since
    the wider scope is visible as heading context of the narrower one.

    Args:
        db_path: Path to SQLite database file
        ref_style: RefStyle for parsing the reference query
        reference_query: Bible reference to find commentary on
        include_headings: Whether to include heading context in results
        query_versification: Versification scheme of the query reference
            (as for :func:`search_database`)

    Returns:
        List of ScopeResult objects in document order. Empty on databases
        without commentary scopes.

    Raises:
        FileNotFoundError: If database doesn't exist
        IncompatibleDatabaseError: If the database is not a compatible
            versiref-search index
        ValueError: If the reference query is invalid or cannot be mapped

    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        db.validate_schema()

        versification_name = db.get_metadata("versification_scheme")
        if not versification_name:
            raise ValueError("Database missing versification_scheme metadata")

        ref = _parse_query_reference(
            ref_style, reference_query, versification_name, query_versification
        )

        # Collect matching scopes, deduplicated by scope id
        matches: dict[int, tuple[int, int]] = {}
        for verse_start, verse_end in ref.range_keys():
            for scope_id, block_start, block_end, _, _ in db.search_scopes(
                verse_start, verse_end
            ):
                matches[scope_id] = (block_start, block_end)

        # Narrowest-first: drop scopes strictly containing another match
        spans = list(matches.values())
        survivors = [
            (start, end)
            for start, end in spans
            if not any(
                (start <= other_start and other_end <= end)
                and (start, end) != (other_start, other_end)
                for other_start, other_end in spans
            )
        ]

        results: list[ScopeResult] = []
        for block_start, block_end in sorted(set(survivors)):
            opening = db.get_content_by_id(block_start)
            if opening is None:
                continue
            _, block_text, _ = opening

            heading_context: dict[int, BlockInfo] = {}
            if include_headings:
                headings = db.get_all_preceding_headings(block_start)
                for level, (heading_id, heading_text) in headings.items():
                    heading_context[level] = BlockInfo(
                        id=heading_id, text=heading_text, heading_level=level
                    )

            results.append(
                ScopeResult(
                    block_start=block_start,
                    block_end=block_end,
                    block_text=block_text,
                    heading_context=heading_context,
                    page=db.get_page_for_block(block_start),
                )
            )

        return results


def get_page_context(
    db_path: str | Path,
    page: str,
    include_headings: bool = True,
    max_blocks: int = DEFAULT_MAX_SECTION_BLOCKS,
) -> list[BlockInfo]:
    """Get the content blocks of a printed page.

    Looks up the ``page`` milestone with the given value and returns the
    blocks from it through the next page milestone (inclusive at both ends,
    since page breaks can fall mid-block). With sparse page milestones the
    span covers everything up to the next *recorded* page, which may be
    several printed pages away; the ``max_blocks`` guard refuses runaway
    spans.

    Args:
        db_path: Path to SQLite database file
        page: Page value to look up (exact match, e.g. "204" or "xvii")
        include_headings: Whether to include preceding headings before the span
        max_blocks: Maximum number of blocks before refusing

    Returns:
        List of BlockInfo objects in document order

    Raises:
        FileNotFoundError: If database doesn't exist
        IncompatibleDatabaseError: If the database is not a compatible
            versiref-search index
        ValueError: If the database has no page milestones or no milestone
            with this value (the message lists nearby recorded pages)
        SectionTooLargeError: If the span exceeds max_blocks

    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        db.validate_schema()

        span = db.get_page_range(page)
        if span is None:
            values = db.get_page_values()
            if not values:
                raise ValueError("Database has no page milestones")
            raise ValueError(
                f"No page milestone '{page}'; {_nearby_pages_hint(page, values)}"
            )
        start_id, end_id = span

        count = db.count_content_range(start_id, end_id)
        if count > max_blocks:
            raise SectionTooLargeError(count, max_blocks)

        blocks: list[BlockInfo] = []
        if include_headings:
            headings = db.get_all_preceding_headings(start_id)
            for level in sorted(headings.keys()):
                heading_id, heading_text = headings[level]
                blocks.append(
                    BlockInfo(id=heading_id, text=heading_text, heading_level=level)
                )

        for block_id, block_text, heading_level in db.get_content_range(
            start_id, end_id
        ):
            blocks.append(
                BlockInfo(id=block_id, text=block_text, heading_level=heading_level)
            )

        return blocks


# Well-formed Roman numeral (subtractive notation), either case.
_ROMAN_RE = re.compile(
    r"(?=[mdclxvi])m*(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})",
    re.IGNORECASE,
)

_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_to_int(s: str) -> int:
    """Convert a well-formed Roman numeral (validated elsewhere) to an int."""
    total = 0
    prev = 0
    for ch in reversed(s.lower()):
        value = _ROMAN_VALUES[ch]
        if value < prev:
            total -= value
        else:
            total += value
        prev = value
    return total


def _page_sort_key(value: str) -> tuple[tuple[int, int], ...] | None:
    """Build a comparison key for a page value, or None if not comparable.

    The value is split into numeric components ("2:84" -> 2, 84), which
    compare component-wise, so volume:page style values order naturally.
    A component is either an Arabic number or a Roman numeral; all Roman
    numerals compare less than all integers (front matter precedes the body).
    Values with any other component (e.g. "A-3") are not comparable.
    """
    parts = re.findall(r"[0-9]+|[a-zA-Z]+", value)
    if not parts:
        return None
    key = []
    for part in parts:
        if part.isdigit():
            key.append((1, int(part)))
        elif _ROMAN_RE.fullmatch(part):
            key.append((0, _roman_to_int(part)))
        else:
            return None
    return tuple(key)


def _nearby_pages_hint(page: str, values: list[str]) -> str:
    """Build a hint naming the recorded pages around a missing page value.

    With sparse page milestones the requested page may fall between two
    recorded ones; when the values are comparable (see
    :func:`_page_sort_key`), say so. Recorded values that are not comparable
    are skipped; if the query itself is not comparable, fall back to the
    recorded range.
    """
    target = _page_sort_key(page)
    keyed = [(k, v) for v in values if (k := _page_sort_key(v)) is not None]
    if target is None or not keyed:
        return f"recorded pages run from '{values[0]}' to '{values[-1]}'"

    equal = next((v for k, v in keyed if k == target), None)
    if equal is not None:
        return f"did you mean '{equal}'?"

    below = max((kv for kv in keyed if kv[0] < target), default=None)
    above = min((kv for kv in keyed if kv[0] > target), default=None)
    if below and above:
        return (
            f"it falls between recorded pages '{below[1]}' and '{above[1]}' "
            f"(try one of those)"
        )
    if below:
        return f"the last recorded page is '{below[1]}'"
    if above:
        return f"the first recorded page is '{above[1]}'"
    return f"recorded pages run from '{values[0]}' to '{values[-1]}'"


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
