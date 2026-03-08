"""Command-line interface for versiref-search."""

import sys
from pathlib import Path
import click
import yaml
from versiref import RefStyle

from .indexer import index_document, get_index_stats
from .searcher import search_database, get_context


def _load_metadata(path: Path) -> dict:
    """Load metadata from a YAML file.

    The file may optionally use YAML front-matter delimiters (``---``).
    """
    text = path.read_text(encoding="utf-8")
    # Strip optional front-matter fences
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[1]
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Metadata file must contain a YAML mapping: {path}")
    return data


@click.group()
@click.version_option()
def main():
    """Search texts for Bible references with versiref."""
    pass


@main.command()
@click.argument(
    "input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "-o",
    "--output",
    "output_file",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output SQLite database file",
)
@click.option(
    "-m",
    "--metadata",
    "metadata_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YAML metadata file (must contain 'title' and 'versification')",
)
@click.option(
    "--style",
    default="en-cmos_short",
    show_default=True,
    help="Named reference style (e.g., en-sbl, en-cmos_short)",
)
@click.option(
    "--skip-abbreviations-check",
    is_flag=True,
    help="Disable checking for unrecognized Bible abbreviations",
)
@click.option(
    "--whitelist",
    default=None,
    help="Comma-separated abbreviations to ignore (e.g., 'PL,SC')",
)
def index(
    input_file, output_file, metadata_file, style, skip_abbreviations_check, whitelist
):
    """Index a Markdown document into a searchable database.

    Creates a SQLite database with indexed Bible references and content blocks
    from INPUT_FILE. Metadata is read from a YAML file specified with -m.
    """
    try:
        ref_style = RefStyle.named(style)
        metadata = _load_metadata(metadata_file)

        whitelist_list = (
            [s.strip() for s in whitelist.split(",")] if whitelist else None
        )

        click.echo(f"Indexing {input_file}...")
        index_document(
            input_path=input_file,
            output_path=output_file,
            metadata=metadata,
            ref_style=ref_style,
            check_abbreviations=not skip_abbreviations_check,
            abbreviation_whitelist=whitelist_list,
        )

        # Get and display stats
        stats = get_index_stats(output_file)
        click.echo(f"✓ Successfully indexed to {output_file}")
        click.echo(f"  Blocks: {stats['block_count']}")
        click.echo(f"  References: {stats['reference_count']}")
        click.echo(f"  Title: {stats['metadata'].get('title', 'N/A')}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument(
    "database", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "-r",
    "--reference",
    help='Bible reference to search for (e.g., "Lk 1:28", "Ps 45:10")',
)
@click.option("-s", "--string", help="Text string to search for (case-insensitive)")
@click.option(
    "--no-headings", is_flag=True, help="Do not include heading context in results"
)
@click.option(
    "--style",
    default="en-cmos_short",
    show_default=True,
    help="Named reference style (e.g., en-sbl, en-cmos_short)",
)
def search(database, reference, string, no_headings, style):
    """Search a database for Bible references and/or text strings.

    At least one of --reference or --string must be provided.
    Results are returned in document order with heading context.
    """
    if not reference and not string:
        click.echo(
            "Error: At least one of --reference or --string must be provided", err=True
        )
        sys.exit(1)

    try:
        ref_style = RefStyle.named(style)

        results = search_database(
            db_path=database,
            ref_style=ref_style,
            reference_query=reference,
            string_query=string,
            include_headings=not no_headings,
        )

        if not results:
            click.echo("No results found.")
            return

        # Display results
        click.echo(f"Found {len(results)} result(s):\n")
        for i, result in enumerate(results, 1):
            if i > 1:
                click.echo("\n" + "=" * 80 + "\n")
            click.echo(result.format_for_display(show_headings=not no_headings))

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument(
    "database", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option("--start", required=True, type=int, help="Starting block ID (inclusive)")
@click.option("--end", required=True, type=int, help="Ending block ID (inclusive)")
@click.option(
    "--include-headings",
    is_flag=True,
    help="Include preceding headings before the range",
)
def context(database, start, end, include_headings):
    """Retrieve a range of content blocks with optional heading context.

    Returns blocks from START to END (inclusive) in document order.
    """
    try:
        blocks = get_context(
            db_path=database,
            start_id=start,
            end_id=end,
            include_headings=include_headings,
        )

        if not blocks:
            click.echo("No blocks found in specified range.")
            return

        # Display blocks
        for i, block in enumerate(blocks):
            if i > 0:
                click.echo()

            if block.heading_level:
                # Display heading with level indicator
                indent = "  " * (block.heading_level - 1)
                click.echo(f"{indent}[Heading {block.heading_level}] {block.text}")
            else:
                # Display regular block with ID
                click.echo(f"[Block {block.id}]")
                click.echo(block.text)

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
