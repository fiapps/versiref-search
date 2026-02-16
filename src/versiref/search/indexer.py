"""Indexing module for versiref-search."""

from pathlib import Path
from typing import Optional
from versiref import Versification, RefParser, RefStyle, standard_names

from .database import Database, SCHEMA_VERSION
from .markdown_parser import parse_markdown


def index_document(
    input_path: str | Path,
    output_path: str | Path,
    versification: str,
    title: str,
    lang: str = "en",
    author: Optional[str] = None,
    name_sets: Optional[list[str]] = None,
    ref_style: Optional[RefStyle] = None,
) -> None:
    """Index a Markdown document into a SQLite database.

    Args:
        input_path: Path to input Markdown file
        output_path: Path to output SQLite database file
        versification: Versification identifier (e.g., "eng", "org")
        title: Document title
        lang: Language code (default: "en")
        author: Optional author name
        name_sets: List of book name set identifiers to recognize (e.g.,
            ["en-sbl_abbreviations", "en-cmos_short"]). If None, uses a
            broad default set. Ignored if ref_style is provided.
        ref_style: Optional RefStyle to use. If provided, name_sets is ignored.

    Raises:
        FileNotFoundError: If input file doesn't exist
        ValueError: If versification is invalid

    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    # Validate input file exists
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Read Markdown content
    markdown_text = input_path.read_text(encoding="utf-8")

    # Setup versiref parser
    try:
        vers = Versification.named(versification)
    except (FileNotFoundError, ValueError) as e:
        raise ValueError(f"Invalid versification '{versification}': {e}")

    # Build reference style
    if ref_style is None:
        # Use provided name sets or sensible defaults
        if name_sets is None:
            # Default: recognize broad range of English abbreviations
            if lang.startswith("en"):
                name_sets = ["en-sbl_abbreviations", "en-cmos_short", "en-sbl_names"]
            else:
                # Default to English for now
                name_sets = ["en-sbl_abbreviations", "en-cmos_short", "en-sbl_names"]

        # Build RefStyle with primary name set
        ref_style = RefStyle(names=standard_names(name_sets[0]))
        # Add additional name sets
        for name_set in name_sets[1:]:
            ref_style.also_recognize(name_set)

    parser = RefParser(ref_style, vers)

    # Parse Markdown into blocks
    blocks = parse_markdown(markdown_text)

    # Create database and populate it
    with Database(output_path) as db:
        # Create schema
        db.create_schema()

        # Set metadata
        db.set_metadata("title", title)
        db.set_metadata("versification_scheme", versification)
        db.set_metadata("lang", lang)
        db.set_metadata("schema_version", SCHEMA_VERSION)
        if author:
            db.set_metadata("author", author)

        # Index each block
        for block in blocks:
            # Insert content block
            content_id = db.insert_content(block.text, block.heading_level)

            # Scan for Bible references in the block text
            for ref, start_pos, end_pos in parser.scan_string(block.text):
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
