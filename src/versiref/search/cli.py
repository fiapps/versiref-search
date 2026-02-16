"""Command-line interface for versiref-search."""

import sys
from pathlib import Path
import click

from .indexer import index_document, get_index_stats
from .searcher import search_database, get_context


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
    "--versification", default="eng", help="Versification scheme (default: eng)"
)
@click.option("--title", required=True, help="Document title")
@click.option("--lang", default="en", help="Language code (default: en)")
@click.option("--author", help="Document author")
@click.option(
    "--name-set",
    "name_sets",
    multiple=True,
    help="Book name set to recognize (can be specified multiple times). "
    "If not specified, defaults to en-sbl_abbreviations, en-cmos_short, "
    "and en-sbl_names.",
)
def index(input_file, output_file, versification, title, lang, author, name_sets):
    """Index a Markdown document into a searchable database.

    Creates a SQLite database with indexed Bible references and content blocks
    from INPUT_FILE.
    """
    try:
        # Convert name_sets tuple to list or None
        name_sets_list = list(name_sets) if name_sets else None

        click.echo(f"Indexing {input_file}...")
        index_document(
            input_path=input_file,
            output_path=output_file,
            versification=versification,
            title=title,
            lang=lang,
            author=author,
            name_sets=name_sets_list,
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
    "--name-set",
    "name_sets",
    multiple=True,
    help="Book name set to recognize (can be specified multiple times)",
)
def search(database, reference, string, no_headings, name_sets):
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
        # Convert name_sets tuple to list or None
        name_sets_list = list(name_sets) if name_sets else None

        results = search_database(
            db_path=database,
            reference_query=reference,
            string_query=string,
            include_headings=not no_headings,
            name_sets=name_sets_list,
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
