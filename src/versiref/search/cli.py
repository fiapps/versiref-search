"""Command-line interface for versiref-search."""

import re
import sys
from importlib.resources import files
from pathlib import Path
import click
import yaml
from versiref import RefStyle, Sensitivity

from .analyzer import analyze_abbreviations, analyze_documents
from .indexer import index_document, get_index_stats
from .models import AbbreviationAnalysis, VersificationScore
from .searcher import (
    AmbiguousSectionError,
    DEFAULT_MAX_SECTION_BLOCKS,
    SectionTooLargeError,
    get_context,
    get_section_by_block,
    get_section_by_heading,
    get_toc,
    search_database,
)


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

        # Resolve invalid_references from config
        invalid_references = config.get("invalid_references", "warn")
        if invalid_references not in ("warn", "exclude", "ignore"):
            raise ValueError(
                f"Invalid invalid_references '{invalid_references}'. "
                f"Valid values: warn, exclude, ignore"
            )

        for input_file in input_files:
            click.echo(f"Indexing {input_file}...")
            index_document(
                input_path=input_file,
                output_path=output_file,
                metadata=metadata,
                ref_style=ref_style,
                parser_sensitivity=parser_sensitivity,
                invalid_references=invalid_references,
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
    default="eng",
    show_default=True,
    help="Versification scheme of the query reference (e.g., eng, lxx).",
)
@click.option(
    "--native",
    is_flag=True,
    help="Parse the reference query in each database's native versification (overrides -v).",
)
@click.option("--xml", is_flag=True, help="Output results in XML-delimited format")
@click.option(
    "--start",
    "start_id",
    type=int,
    default=None,
    help="Only search blocks with ID >= START (inclusive)",
)
@click.option(
    "--end",
    "end_id",
    type=int,
    default=None,
    help="Only search blocks with ID <= END (inclusive)",
)
def search(
    databases: tuple[Path, ...],
    reference: str | None,
    string: str | None,
    no_headings: bool,
    style: str,
    versification: str,
    native: bool,
    xml: bool,
    start_id: int | None,
    end_id: int | None,
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

    if start_id is not None and end_id is not None and start_id > end_id:
        click.echo("Error: --start must not exceed --end", err=True)
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
                query_versification=None if native else versification,
                start_id=start_id,
                end_id=end_id,
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
@click.argument("name", required=False)
def docs(name: str | None) -> None:
    """Print the filesystem path to the bundled documentation.

    With no argument, prints the path to the bundled docs directory. Pass a
    file NAME (e.g., searching.md) to print the path to that single doc.
    """
    docs_dir = files("versiref.search") / "docs"
    if name is not None:
        target = docs_dir / name
        if not target.is_file():
            click.echo(f"Error: no such doc: {name}", err=True)
            sys.exit(1)
        click.echo(str(target))
    else:
        click.echo(str(docs_dir))


@main.command()
@click.argument(
    "database", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--start",
    type=int,
    default=None,
    help="Starting block ID (inclusive)",
)
@click.option(
    "--end",
    type=int,
    default=None,
    help="Ending block ID (inclusive)",
)
@click.option(
    "--section",
    "section_level",
    type=int,
    default=None,
    help=(
        "Retrieve a whole section at heading LEVEL (1-6). Anchor it with "
        "--start (block) or --heading (text); add --end to span sections."
    ),
)
@click.option(
    "--heading",
    "heading_text",
    default=None,
    help="Select a section by matching its heading text (use with --section)",
)
@click.option(
    "--max-blocks",
    type=int,
    default=DEFAULT_MAX_SECTION_BLOCKS,
    show_default=True,
    help="Refuse to return a section larger than this many blocks",
)
@click.option(
    "--include-headings",
    is_flag=True,
    help="Include the headings above the range/section",
)
def show(
    database: Path,
    start: int | None,
    end: int | None,
    section_level: int | None,
    heading_text: str | None,
    max_blocks: int,
    include_headings: bool,
) -> None:
    r"""Retrieve content blocks from a database.

    Three modes:

    \b
      Range:           --start S --end E
      Section by block: --start S --section L  (add --end to span sections)
      Section by text:  --heading TEXT --section L

    Blocks are returned in document order.
    """
    try:
        if section_level is not None:
            if heading_text is not None:
                if start is not None or end is not None:
                    raise click.UsageError(
                        "--heading cannot be combined with --start/--end"
                    )
                blocks = get_section_by_heading(
                    db_path=database,
                    heading_text=heading_text,
                    level=section_level,
                    include_headings=include_headings,
                    max_blocks=max_blocks,
                )
            else:
                if start is None:
                    raise click.UsageError(
                        "--section requires --start (block) or --heading (text)"
                    )
                if end is not None and end < start:
                    raise click.UsageError("--end must not be less than --start")
                blocks = get_section_by_block(
                    db_path=database,
                    block_id=start,
                    level=section_level,
                    end_id=end,
                    include_headings=include_headings,
                    max_blocks=max_blocks,
                )
        else:
            if heading_text is not None:
                raise click.UsageError("--heading requires --section LEVEL")
            if start is None or end is None:
                raise click.UsageError(
                    "--start and --end are required (or use --section)"
                )
            if start > end:
                raise click.UsageError("--start must not exceed --end")
            blocks = get_context(
                db_path=database,
                start_id=start,
                end_id=end,
                include_headings=include_headings,
            )

        if not blocks:
            click.echo("No blocks found.")
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

    except click.UsageError:
        raise
    except SectionTooLargeError as e:
        click.echo(
            f"Error: section has {e.block_count} blocks (max {e.max_blocks}).\n"
            "Raise --max-blocks or use a deeper --section level.",
            err=True,
        )
        sys.exit(1)
    except AmbiguousSectionError as e:
        click.echo(
            "Error: multiple headings match; re-run with --start using one of "
            "these block IDs:",
            err=True,
        )
        for candidate in e.candidates:
            click.echo(f"  {candidate.text.strip()} {{block={candidate.id}}}", err=True)
        sys.exit(1)
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
    "--depth",
    type=int,
    default=2,
    show_default=True,
    help="Maximum heading level to include (1-6)",
)
@click.option(
    "--start",
    "start_id",
    type=int,
    default=None,
    help="Only include headings with block ID >= START (inclusive)",
)
@click.option(
    "--end",
    "end_id",
    type=int,
    default=None,
    help="Only include headings with block ID <= END (inclusive)",
)
@click.option("--xml", is_flag=True, help="Output results in XML-delimited format")
def toc(
    database: Path,
    depth: int,
    start_id: int | None,
    end_id: int | None,
    xml: bool,
) -> None:
    """Print a table of contents (headings) for DATABASE.

    Outputs every heading whose level is <= --depth (default 2), in document
    order. Use --start/--end to restrict to a range of block IDs.
    """
    if start_id is not None and end_id is not None and start_id > end_id:
        click.echo("Error: --start must not exceed --end", err=True)
        sys.exit(1)

    try:
        headings = get_toc(
            db_path=database, depth=depth, start_id=start_id, end_id=end_id
        )

        if xml:
            click.echo("<toc>")
            for heading in headings:
                click.echo(f'<block n="{heading.id}">')
                click.echo(heading.text)
                click.echo("</block>")
            click.echo("</toc>")
            return

        if not headings:
            click.echo("No headings found.")
            return

        for heading in headings:
            click.echo(f"{heading.text} {{block={heading.id}}}")

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
    "input_files",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "-c",
    "--config",
    "config_file",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="YAML config file (same format as the index command)",
)
@click.option(
    "--style",
    default=None,
    help="Named reference style (overrides config) [default: en-cmos_short]",
)
@click.option(
    "--sensitivity",
    default=None,
    type=click.Choice([s.name.lower() for s in Sensitivity], case_sensitive=False),
    help="Reference scanner sensitivity (overrides config) [default: verse]",
)
def analyze(
    input_files: tuple[Path, ...],
    config_file: Path | None,
    style: str | None,
    sensitivity: str | None,
) -> None:
    """Analyze INPUT_FILES for abbreviations and versification scheme.

    First reports book abbreviations the configured ``--style`` does not
    recognize and, where possible, recommends bundled standard-name sets
    that would cover them. Then ranks every named versification by the
    fraction of parsed references that are valid in it.

    When a config file is supplied, the ``style``, ``parser_sensitivity``,
    and ``abbreviations_whitelist`` keys take effect, and the
    ``versification`` key (either set directly or pulled from the linked
    metadata file) is flagged with ``*`` in the ranking.
    """
    try:
        config: dict = {}
        if config_file is not None:
            config = _load_config(config_file)

        # Resolve style: CLI --style overrides config.
        if style is not None:
            ref_style = RefStyle.named(style)
        else:
            style_value = config.get("style")
            if style_value is None:
                ref_style = RefStyle.named("en-cmos_short")
            elif isinstance(style_value, dict):
                ref_style = RefStyle.from_dict(style_value)
            else:
                ref_style = RefStyle.named(style_value)

        # Resolve sensitivity: CLI --sensitivity overrides config.
        sensitivity_value = sensitivity or config.get("parser_sensitivity") or "verse"
        try:
            parser_sensitivity = Sensitivity[sensitivity_value.upper()]
        except KeyError:
            valid = ", ".join(s.name.lower() for s in Sensitivity)
            raise ValueError(
                f"Invalid parser_sensitivity '{sensitivity_value}'. "
                f"Valid values: {valid}"
            )

        # Whitelist comes from the config only.
        whitelist = config.get("abbreviations_whitelist")

        # Configured versification for highlighting in the ranking. Pull
        # from the config or, failing that, the metadata file it points to.
        configured_vers = _resolve_configured_versification(config)

        click.echo(f"Analyzed {len(input_files)} file(s).\n")

        abbrev = analyze_abbreviations(
            input_paths=input_files,
            ref_style=ref_style,
            abbreviation_whitelist=whitelist,
        )
        _emit_abbreviation_section(abbrev, ref_style)

        for set_name in abbrev.needed_sets:
            ref_style.also_recognize(set_name)

        scores = analyze_documents(
            input_paths=input_files,
            ref_style=ref_style,
            parser_sensitivity=parser_sensitivity,
        )

        total = scores[0].total if scores else 0
        click.echo()
        if total == 0:
            click.echo(
                "Reference pool: 0 reference(s); skipping versification ranking."
            )
            if not abbrev.unrecognized:
                sys.exit(1)
            return

        click.echo(f"Reference pool: {total} reference(s).\n")

        _emit_ranking(scores, configured_vers)

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


def _resolve_configured_versification(config: dict) -> str | None:
    """Find the configured versification, if any, for the analyze ranking marker.

    Prefers ``config["versification"]``; falls back to the ``versification``
    key in the metadata file the config points to. Errors loading metadata
    are swallowed — the marker is a UX nicety, not a correctness gate.
    """
    if "versification" in config:
        value = config["versification"]
        return str(value) if value is not None else None
    meta_path = config.get("metadata")
    if meta_path is None:
        return None
    try:
        metadata = _load_metadata(Path(meta_path))
    except (OSError, ValueError, yaml.YAMLError):
        return None
    value = metadata.get("versification")
    return str(value) if value is not None else None


def _emit_ranking(
    scores: list[VersificationScore], configured_vers: str | None
) -> None:
    """Print the versification ranking table, marking the configured one."""
    # Versification names are case-insensitive (e.g., "Vulgata" matches
    # "vulgata"); resolve to the canonical name used in the score table.
    by_lower = {s.name.lower(): s.name for s in scores}
    marked = (
        by_lower.get(configured_vers.lower()) if configured_vers is not None else None
    )

    name_width = max(len("Versification"), max(len(s.name) for s in scores))
    valid_width = max(len("Valid"), max(len(str(s.valid)) for s in scores))
    total_width = max(len("Total"), max(len(str(s.total)) for s in scores))

    header = (
        f"  {'Versification':<{name_width}}  "
        f"{'Valid':>{valid_width}}  "
        f"{'Total':>{total_width}}  "
        f"Score"
    )
    click.echo(header)
    for s in scores:
        marker = "*" if s.name == marked else " "
        click.echo(
            f"{marker} {s.name:<{name_width}}  "
            f"{s.valid:>{valid_width}}  "
            f"{s.total:>{total_width}}  "
            f"{s.score * 100:5.1f}%"
        )

    if marked is not None:
        click.echo()
        click.echo(f"* configured versification ({marked})")
    elif configured_vers is not None:
        click.echo()
        click.echo(
            f"Note: configured versification '{configured_vers}' is not a known scheme."
        )


def _emit_abbreviation_section(
    abbrev: AbbreviationAnalysis, ref_style: RefStyle
) -> None:
    """Print the abbreviation analysis section to stdout."""
    if not abbrev.unrecognized:
        click.echo("All abbreviations are recognized by the configured style.")
        return

    identifier = ref_style.identifier or ""
    match = re.match(r"^([a-z]{2,3})-", identifier)
    glob = f"{match.group(1)}-*" if match else "*"

    if abbrev.needed_sets:
        click.echo(f"Additional book-name sets needed ({glob}):")
        for name in abbrev.needed_sets:
            click.echo(f"  {name}")
    if abbrev.remaining:
        click.echo()
        click.echo(
            "Names not covered by any set: " + ", ".join(sorted(abbrev.remaining))
        )


if __name__ == "__main__":
    main()
