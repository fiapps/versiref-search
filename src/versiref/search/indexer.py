"""Indexing module for versiref-search."""

import logging
import re
from typing import Literal
from pathlib import Path
from versiref import Versification, RefParser, RefStyle, Sensitivity

from .database import Database, PRODUCT_NAME, SCHEMA_VERSION
from .markdown_parser import parse_markdown

logger = logging.getLogger(__name__)

InvalidRefAction = Literal["warn", "exclude", "ignore"]


def find_unrecognized_abbreviations(
    text: str,
    ref_style: RefStyle,
    whitelist: list[str] | None = None,
) -> dict[str, str]:
    """Find potential Bible abbreviations not recognized by the ref_style.

    Scans text with a regex for patterns that look like Bible references
    (e.g., "Lk 1:28", "1 Sam 3:4") and reports any whose book abbreviation
    is not in ref_style.recognized_names.

    Args:
        text: The text to scan.
        ref_style: RefStyle whose recognized_names are checked.
        whitelist: Optional list of abbreviations to ignore.

    Returns:
        Dict mapping each unrecognized abbreviation to an example of its usage.

    """
    sep = re.escape(ref_style.chapter_verse_separator)
    pattern = rf"((?:[1-4]|[IV]+)\s+)?(\w[\w()]*)\s+\d+{sep}\d+"
    whitelist_set = set(whitelist) if whitelist else set()
    unrecognized: dict[str, str] = {}
    for match in re.finditer(pattern, text):
        leading = match.group(1)
        book_name = match.group(2)
        if leading:
            abbrev = leading + book_name  # e.g., "1 Sam"
        else:
            abbrev = book_name
        # Skip if the book_name part is purely digits (e.g. "1 39:243" is not a reference)
        if book_name.isdigit():
            continue
        # Skip if recognized (check full abbrev, or book_name part for numbered books)
        if abbrev in ref_style.recognized_names:
            continue
        if leading and book_name in ref_style.recognized_names:
            continue
        if abbrev in whitelist_set:
            continue
        # Also skip if the book_name part alone is whitelisted (covers "1 PL", "3 PL", etc.)
        if leading and book_name in whitelist_set:
            continue
        if abbrev not in unrecognized:
            unrecognized[abbrev] = match.group(0)
    for abbrev, example in unrecognized.items():
        logger.warning('Unrecognized abbreviation "%s" in "%s".', abbrev, example)
    return unrecognized


def _insert_scopes(
    db: Database,
    block_start: int,
    block_end: int,
    ranges: list[tuple[int, int]],
) -> None:
    """Insert one commentary_scope row per verse range for a block span."""
    for verse_start, verse_end in ranges:
        db.insert_scope(block_start, block_end, verse_start, verse_end)


def _scope_ranges(
    parser: RefParser,
    vers: Versification,
    versification: str,
    value: str,
) -> list[tuple[int, int]]:
    """Resolve an explicit scope marker's reference into verse range keys.

    Applies the same filters as the main reference scan: books must be in
    the database's versification, and references tagged with a foreign
    versification are mapped into it. Warns and returns an empty list when
    the reference cannot be used.
    """
    try:
        ref = parser.parse(value, silent=True)
    except Exception:
        ref = None
    if ref is None:
        logger.warning('Scope reference "%s" could not be parsed; ignoring.', value)
        return []
    if not all(vers.includes(sr.book_id) for sr in ref.simple_refs):
        logger.warning(
            'Scope reference "%s" refers to a book not in the '
            '"%s" versification; ignoring.',
            value,
            versification,
        )
        return []
    if ref.versification is not None and ref.versification.identifier != versification:
        mapped = ref.map_to(vers)
        if mapped is None:
            logger.warning(
                'Scope reference "%s" in versification "%s" could not be '
                'mapped to "%s"; ignoring.',
                value,
                ref.versification.identifier,
                versification,
            )
            return []
        ref = mapped
    return list(ref.range_keys())


def _normalize_metadata_value(value: object) -> str:
    """Normalize a metadata value to a string.

    Lists are joined with " and " (similar to BibTeX name fields).
    """
    if isinstance(value, list):
        return " and ".join(str(v) for v in value)
    return str(value)


def index_document(
    input_path: str | Path,
    output_path: str | Path,
    metadata: dict[str, object],
    ref_style: RefStyle,
    *,
    parser_sensitivity: Sensitivity = Sensitivity.VERSE,
    invalid_references: InvalidRefAction = "warn",
    check_abbreviations: bool = True,
    abbreviation_whitelist: list[str] | None = None,
    append: bool = False,
    commentary_headings: bool = False,
) -> None:
    """Index a Markdown document into a SQLite database.

    Args:
        input_path: Path to input Markdown file
        output_path: Path to output SQLite database file
        metadata: Document metadata dict. Must contain "title" and
            "versification" keys. Values may be strings or lists
            (lists are joined with " and ").
        ref_style: RefStyle to use for parsing Bible references
        parser_sensitivity: Sensitivity level for reference scanning
        invalid_references: How to handle invalid references (out-of-range
            chapter/verse): "warn" to log and include, "exclude" to log and
            skip, "ignore" to include silently. References to books not in
            the versification are always excluded.
        check_abbreviations: If True, warn about unrecognized abbreviations
        abbreviation_whitelist: Abbreviations to exclude from the check
        append: If False (default), any existing database at output_path is
            replaced so the result reflects only this document. If True, the
            document's blocks and references are added to the existing
            database (used to combine several documents into one index).
        commentary_headings: If True, headings containing Bible references
            open commentary scopes: the referenced passage is recorded as the
            subject of the section the heading opens (through the next
            heading at the same or a shallower level).

    Raises:
        FileNotFoundError: If input file doesn't exist
        ValueError: If versification is invalid or required keys missing

    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    # Validate required metadata keys
    for key in ("title", "versification"):
        if key not in metadata:
            raise ValueError(f"Metadata must contain '{key}'")

    versification = str(metadata["versification"])

    # Validate input file exists
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Read Markdown content
    markdown_text = input_path.read_text(encoding="utf-8")

    # Check for unrecognized abbreviations
    if check_abbreviations:
        find_unrecognized_abbreviations(
            markdown_text, ref_style, abbreviation_whitelist
        )

    # Setup versiref parser
    try:
        vers = Versification.named(versification)
    except (FileNotFoundError, ValueError) as e:
        raise ValueError(f"Invalid versification '{versification}': {e}")

    parser = RefParser(ref_style, vers)

    # Parse Markdown into blocks
    blocks = parse_markdown(markdown_text)

    # Replace any existing database unless appending, so a rebuild reflects
    # only the current source rather than accumulating duplicate blocks.
    # Done after all validation/parsing so a failed call leaves the old
    # database untouched.
    if not append and output_path.exists():
        output_path.unlink()

    # Create database and populate it
    with Database(output_path) as db:
        # Create schema
        db.create_schema()

        # Set metadata
        db.set_metadata("format", PRODUCT_NAME)
        db.set_metadata("schema_version", SCHEMA_VERSION)
        db.set_metadata("versification_scheme", versification)
        for key, value in metadata.items():
            if key == "versification":
                continue  # already stored as versification_scheme
            db.set_metadata(key, _normalize_metadata_value(value))

        # Index each block
        reference_count = 0
        # Commentary-scope state. Heading-derived scopes nest via heading
        # levels; explicit <!-- scope: ... --> markers form one non-nesting
        # scope at a time. Entries are (level, block_start, ranges) and
        # (block_start, ranges) respectively.
        open_heading_scopes: list[tuple[int, int, list[tuple[int, int]]]] = []
        open_explicit: tuple[int, list[tuple[int, int]]] | None = None
        last_content_id: int | None = None

        for block in blocks:
            # Insert content block
            content_id = db.insert_content(block.text, block.heading_level)
            last_content_id = content_id

            # A heading closes every open heading scope at its own level or
            # deeper; those sections end at the previous block.
            if block.heading_level is not None and open_heading_scopes:
                still_open = []
                for level, scope_start, ranges in open_heading_scopes:
                    if level >= block.heading_level:
                        _insert_scopes(db, scope_start, content_id - 1, ranges)
                    else:
                        still_open.append((level, scope_start, ranges))
                open_heading_scopes = still_open

            # Verse ranges found in this block (used for heading scopes)
            block_ranges: list[tuple[int, int]] = []

            # Scan for Bible references in the block text
            for ref, start_pos, end_pos in parser.scan_string(
                block.text, sensitivity=parser_sensitivity
            ):
                # Check if all books in the ref are in the versification
                if not all(vers.includes(sr.book_id) for sr in ref.simple_refs):
                    ref_text = block.text[start_pos:end_pos]
                    logger.warning(
                        'Reference "%s" refers to a book not in the '
                        '"%s" versification; excluding.',
                        ref_text,
                        versification,
                    )
                    continue

                # Check validity (out-of-range chapter/verse)
                if not ref.is_valid():
                    ref_text = block.text[start_pos:end_pos]
                    if invalid_references == "exclude":
                        logger.warning(
                            'Invalid reference "%s"; excluding.',
                            ref_text,
                        )
                        continue
                    elif invalid_references == "warn":
                        logger.warning(
                            'Invalid reference "%s"; including anyway.',
                            ref_text,
                        )

                # The scanner may tag a reference with a foreign versification
                # (e.g. "Ps 50:1 Vulg."). Map it into the database's scheme so
                # range keys are derived in the database's versification.
                if (
                    ref.versification is not None
                    and ref.versification.identifier != versification
                ):
                    mapped = ref.map_to(vers)
                    if mapped is None:
                        ref_text = block.text[start_pos:end_pos]
                        logger.warning(
                            'Reference "%s" in versification "%s" could not be '
                            'mapped to "%s"; excluding.',
                            ref_text,
                            ref.versification.identifier,
                            versification,
                        )
                        continue
                    ref = mapped

                # Convert reference to integer range keys
                for verse_start, verse_end in ref.range_keys():
                    # Insert reference index entry
                    db.insert_reference(
                        content_id=content_id,
                        verse_start=verse_start,
                        verse_end=verse_end,
                        char_start=start_pos,
                        char_end=end_pos,
                    )
                    reference_count += 1
                    block_ranges.append((verse_start, verse_end))

            # A heading with references opens a commentary scope for the
            # section it introduces.
            if commentary_headings and block.heading_level is not None and block_ranges:
                open_heading_scopes.append(
                    (block.heading_level, content_id, block_ranges)
                )

            # Milestones extracted from this block's source text
            for milestone in block.milestones:
                if milestone.type in ("page", "marg"):
                    db.insert_milestone(
                        milestone.type, milestone.value, content_id, milestone.offset
                    )
                elif milestone.type == "scope":
                    if open_explicit is not None:
                        # A new scope marker (or "end") closes the open one.
                        # A marker at offset 0 stood before this block, so the
                        # closing scope excludes it; an inline marker shares
                        # the block.
                        scope_start, ranges = open_explicit
                        scope_end = (
                            content_id if milestone.offset > 0 else content_id - 1
                        )
                        _insert_scopes(
                            db, scope_start, max(scope_end, scope_start), ranges
                        )
                        open_explicit = None
                    if milestone.value.strip().lower() != "end":
                        ranges = _scope_ranges(
                            parser, vers, versification, milestone.value
                        )
                        if ranges:
                            open_explicit = (content_id, ranges)

        # Close scopes still open at the end of the document.
        if last_content_id is not None:
            for _, scope_start, ranges in open_heading_scopes:
                _insert_scopes(db, scope_start, last_content_id, ranges)
            if open_explicit is not None:
                scope_start, ranges = open_explicit
                _insert_scopes(db, scope_start, last_content_id, ranges)

        if reference_count == 0:
            logger.warning(
                "No references were indexed from %s. "
                "If no unrecognized abbreviation warnings appeared, "
                "the configured style may not match the document's citation format.",
                input_path.name,
            )


def get_index_stats(db_path: str | Path) -> dict:
    """Get statistics about an indexed database.

    Args:
        db_path: Path to SQLite database file

    Returns:
        Dictionary with statistics (block_count, reference_count,
        milestone_count, scope_count, metadata)

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
        return {
            "block_count": db.count_content_blocks(),
            "reference_count": db.count_references(),
            "milestone_count": db.count_milestones(),
            "scope_count": db.count_scopes(),
            "metadata": db.get_all_metadata(),
        }
