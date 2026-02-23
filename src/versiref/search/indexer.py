"""Indexing module for versiref-search."""

from pathlib import Path
from versiref import Versification, RefParser, RefStyle

from .database import Database, SCHEMA_VERSION
from .markdown_parser import parse_markdown


def index_document(
    input_path: str | Path,
    output_path: str | Path,
    versification: str,
    title: str,
    ref_style: RefStyle,
    lang: str = "en",
    author: str | None = None,
) -> None:
    """Index a Markdown document into a SQLite database.

    Args:
        input_path: Path to input Markdown file
        output_path: Path to output SQLite database file
        versification: Versification identifier (e.g., "eng", "org")
        title: Document title
        ref_style: RefStyle to use for parsing Bible references
        lang: Language code (default: "en")
        author: Optional author name

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
