"""Indexing module for versiref-search."""

import logging
import re
from typing import Literal
from pathlib import Path
from versiref import Versification, RefParser, RefStyle, Sensitivity

from .database import Database, SCHEMA_VERSION
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

    # Create database and populate it
    with Database(output_path) as db:
        # Create schema
        db.create_schema()

        # Set metadata
        db.set_metadata("schema_version", SCHEMA_VERSION)
        db.set_metadata("versification_scheme", versification)
        for key, value in metadata.items():
            if key == "versification":
                continue  # already stored as versification_scheme
            db.set_metadata(key, _normalize_metadata_value(value))

        # Index each block
        for block in blocks:
            # Insert content block
            content_id = db.insert_content(block.text, block.heading_level)

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


def get_index_stats(db_path: str | Path) -> dict:
    """Get statistics about an indexed database.

    Args:
        db_path: Path to SQLite database file

    Returns:
        Dictionary with statistics (block_count, reference_count, metadata)

    Raises:
        FileNotFoundError: If database doesn't exist

    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with Database(db_path) as db:
        return {
            "block_count": db.count_content_blocks(),
            "reference_count": db.count_references(),
            "metadata": db.get_all_metadata(),
        }
