"""Command-line interface for versiref-search."""

import sys
from pathlib import Path
import click
import yaml
from versiref import RefStyle, Sensitivity

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


def _load_config(path: Path) -> dict:
    """Load an indexing config from a YAML file.

    Resolves the ``metadata`` path relative to the config file's directory.
    """
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    # Resolve metadata path relative to config file location
    if "metadata" in data and data["metadata"] is not None:
        data["metadata"] = path.parent / data["metadata"]
    return data


@click.group()
@click.version_option(package_name="versiref-search")
def main() -> None:
    """Search texts for Bible references with versiref."""
    pass


@main.command()
@click.argument(
    "input_files",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
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
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YAML metadata file (must contain 'title' and 'versification')",
)
@click.option(
    "-c",
    "--config",
    "config_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YAML config file with indexing options (metadata, style, whitelist, etc.)",
)
@click.option(
    "--style",
    default=None,
    help="Named reference style (e.g., en-sbl, en-cmos_short) [default: en-cmos_short]",
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
    input_files: tuple[Path, ...],
    output_file: Path,
    metadata_file: Path | None,
    config_file: Path | None,
    style: str | None,
    skip_abbreviations_check: bool,
    whitelist: str | None,
) -> None:
    """Index one or more Markdown documents into a searchable database.

    Creates a SQLite database with indexed Bible references and content blocks
    from INPUT_FILES. Each file is indexed separately and appended to the
    database in order. Metadata is read from a YAML file specified with -m or
    from a config file specified with -c.
    """
    try:
        config: dict = {}
        if config_file is not None:
            config = _load_config(config_file)

        # Resolve metadata: CLI --metadata overrides config
        meta_path = metadata_file or config.get("metadata")
        if meta_path is None:
            raise click.UsageError(
                "Metadata must be provided via --metadata or in the config file."
            )
        metadata = _load_metadata(Path(meta_path))

        # Supply versification from config
        if "versification" in config:
            metadata["versification"] = config["versification"]

        # Resolve style: CLI --style overrides config
        style_value = style if style is not None else config.get("style")
        if style_value is None:
            style_value = "en-cmos_short"
        if isinstance(style_value, dict):
            ref_style = RefStyle.from_dict(style_value)
        else:
            ref_style = RefStyle.named(style_value)

        # Resolve whitelist: CLI --whitelist overrides config
        if whitelist is not None:
            whitelist_list = [s.strip() for s in whitelist.split(",")]
        elif "abbreviations_whitelist" in config:
            whitelist_list = config["abbreviations_whitelist"]
        else:
            whitelist_list = None

        # Resolve skip_abbreviations_check: CLI flag overrides config
        if not skip_abbreviations_check and config.get("skip_abbreviations_check"):
            skip_abbreviations_check = True

        # Resolve parser_sensitivity from config
        sensitivity_value = config.get("parser_sensitivity", "verse")
        try:
            parser_sensitivity = Sensitivity[sensitivity_value.upper()]
        except KeyError:
            valid = ", ".join(s.name.lower() for s in Sensitivity)
            raise ValueError(
                f"Invalid parser_sensitivity '{sensitivity_value}'. "
                f"Valid values: {valid}"
            )

        for input_file in input_files:
            click.echo(f"Indexing {input_file}...")
            index_document(
                input_path=input_file,
                output_path=output_file,
                metadata=metadata,
                ref_style=ref_style,
                parser_sensitivity=parser_sensitivity,
                check_abbreviations=not skip_abbreviations_check,
                abbreviation_whitelist=whitelist_list,
            )

        # Get and display stats
        stats = get_index_stats(output_file)
        click.echo(f"✓ Successfully indexed to {output_file}")
        click.echo(f"  Blocks: {stats['block_count']}")
        click.echo(f"  References: {stats['reference_count']}")
        click.echo(f"  Title: {stats['metadata'].get('title', 'N/A')}")

    except click.UsageError:
        raise
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(1)


def _output_search_plain(
    all_db_results: list[tuple[Path, list]],
    total_count: int,
    show_headings: bool,
) -> None:
    """Output search results in plain text format."""
    multi = len(all_db_results) > 1

    for db_index, (database, results) in enumerate(all_db_results):
        if multi:
            if db_index > 0:
                click.echo()
            click.echo(f"--- {database.stem} ---")
            if not results:
                click.echo("No results found.")
                continue
            click.echo(f"Found {len(results)} result(s):\n")
        else:
            if not results:
                click.echo("No results found.")
                return
            click.echo(f"Found {len(results)} result(s):\n")

        for i, result in enumerate(results, 1):
            if i > 1:
                click.echo("\n" + "=" * 80 + "\n")
            click.echo(result.format_for_display(show_headings=show_headings))

    if multi and total_count == 0:
        click.echo("\nNo results found in any database.")


def _output_search_xml(
    all_db_results: list[tuple[Path, list]],
    total_count: int,
    show_headings: bool,
) -> None:
    """Output search results in XML-delimited format."""
    click.echo(f'<search-results count="{total_count}">')

    for database, results in all_db_results:
        click.echo(f'<source db="{database.stem}">')
        for result in results:
            click.echo(result.format_xml(show_headings=show_headings))
        click.echo("</source>")

    click.echo("</search-results>")


@main.command()
@click.argument(
    "databases",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
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
@click.option(
    "-v",
    "--versification",
    default=None,
    help="Versification scheme of the query reference (e.g., eng, lxx). "
    "When set, the reference is mapped to the database's scheme automatically.",
)
@click.option("--xml", is_flag=True, help="Output results in XML-delimited format")
def search(
    databases: tuple[Path, ...],
    reference: str | None,
    string: str | None,
    no_headings: bool,
    style: str,
    versification: str | None,
    xml: bool,
) -> None:
    """Search one or more databases for Bible references and/or text strings.

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
        total_count = 0

        all_db_results: list[tuple[Path, list]] = []
        for database in databases:
            results = search_database(
                db_path=database,
                ref_style=ref_style,
                reference_query=reference,
                string_query=string,
                include_headings=not no_headings,
                query_versification=versification,
            )
            total_count += len(results)
            all_db_results.append((database, results))

        if xml:
            _output_search_xml(all_db_results, total_count, not no_headings)
        else:
            _output_search_plain(all_db_results, total_count, not no_headings)

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
    "databases",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
def info(databases: tuple[Path, ...]) -> None:
    """Display metadata and statistics for one or more databases."""
    try:
        for db_index, database in enumerate(databases):
            if db_index > 0:
                click.echo()
            if len(databases) > 1:
                click.echo(f"--- {database.stem} ---")
            stats = get_index_stats(database)
            for key, value in stats["metadata"].items():
                click.echo(f"  {key}: {value}")
            click.echo(f"  blocks: {stats['block_count']}")
            click.echo(f"  references: {stats['reference_count']}")
    except FileNotFoundError as e:
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
def context(database: Path, start: int, end: int, include_headings: bool) -> None:
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
