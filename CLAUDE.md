# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**versiref-search** is a Python package for indexing and searching text documents (primarily theological/biblical texts in Markdown format) for Bible references and text strings. It extends the [versiref](https://github.com/fiapps/versiref) ecosystem.

- **Package name**: `versiref.search` (namespace package)
- **PyPI name**: `versiref-search`
- **Purpose**: Build SQLite-indexed versions of Markdown texts for fast Bible reference searching with range overlap matching

## Development Commands

### Package Management
```bash
# Install dependencies and sync environment
uv sync

# Add a new dependency
uv add <package-name>

# Build the package
uv build

# Run Python with the project environment
uv run python
```

### Type Checking and Linting
```bash
# Run mypy for type checking (strict mode)
uv run mypy src/

# Lint and format
uv run ruff check
uv run ruff format
```

The mypy and ruff settings follow versiref's: strict mypy, and the D, E, W, F, I, B, UP, SIM, C4, PT, and RUF rule sets.
Two things differ because this package needs them: the mypy namespace-package settings, and the exemption of tests from the docstring rules D101–D103.

### Testing
Tests live in `tests/`. Run with:
```bash
uv run pytest
```

### Dependency auditing

Supply-chain checks run at two points: when upgrading dependencies and before tagging a release. See `SECURITY.md` for the threat model and rationale; the commands are:

**Upgrade with a 7-day cooldown** (hijacked releases are usually detected and yanked within that window):

```sh
uv lock --upgrade --exclude-newer "$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)"
```

The date expression above is for BSD `date` (macOS). On GNU `date`: `date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ`.

**First-party exception:** `versiref` is published by the same maintainer as versiref-search and is exempt from the cooldown. After the cooldown-bound upgrade, pick up any newer `versiref` release:

```sh
uv lock --upgrade-package versiref
```

**CVE exception:** if a CVE is announced for a current dependency, bypass the cooldown and upgrade immediately — a known-bad version is worse than an unquarantined good one.

**Scan the locked dependencies for known advisories:**

```sh
uv export --format requirements-txt --no-emit-project | uvx pip-audit -r /dev/stdin --disable-pip --require-hashes
```

`--disable-pip` tells pip-audit to trust the pinned+hashed list from `uv export` rather than spinning up its own venv (which fails on uv-managed Python since ensurepip is disabled there).

Run after any lockfile change and before each release.

## Architecture

### Core Data Model

The system uses SQLite databases (one per index, built from one or more source documents) with these tables:

1. **content**: Stores Markdown blocks in document order
   - `id`: Sequential primary key (determines display order)
   - `block_text`: Markdown text for one block-level element, with milestone comments stripped
   - `heading_level`: Integer 1-6 for headings, NULL otherwise

2. **content_fts**: FTS5 virtual table for full-text search on `block_text`
   - Synced with `content` via triggers (insert/update/delete)
   - Provides word-boundary matching (not substring) and `highlight()` for `<mark>` tag wrapping

3. **reference_index**: Bible reference positions and ranges
   - `content_id`: References the content block
   - `verse_start`/`verse_end`: 10-digit integer encodings of verse ranges
   - `char_start`/`char_end`: Character positions in block_text
   - Multiple rows per content block if multiple references exist

4. **milestone**: Point markers in the text: `(type, value, content_id, char_offset)`
   - Types `page`, `marg`, and `date` come from `<!-- type: value -->` comments in the source (and `date` from frontmatter); a value stays in effect until the next one of its type
   - The value `end` ends a run, leaving no value in effect
   - Type `document` is written by the indexer at the first block of each source file, with the file name as its value; milestone and heading lookups stop at this boundary

5. **commentary_scope**: Which passage a span of blocks comments on: `(block_start, block_end, verse_start, verse_end)`
   - From `<!-- scope: ... -->` markers, or from headings when `commentary_headings` is set

6. **metadata**: Key-value pairs (title, lang, author, etc.)
   - `format`, `schema_version`, and `versification_scheme` are written by the indexer and cannot be set from a metadata file

The schema version (`SCHEMA_VERSION` in `database.py`, currently 3.0) is independent of the package version.
A minor bump is additive; a major bump rejects older databases and requires re-indexing.

### Verse Encoding

Bible references use 10-digit integers: `BBCCCVVVSS`
- BB: Book number (01-99) according to versification scheme
- CCC: Chapter number (001-999)
- VVV: Verse number (001-999)
- SS: Subverse ordinal (00-99) for inserted verses (e.g., the Greek additions to Esther, ESG 4:17a-z); collapses to 00 for a plain verse or a mere portion of one

Example: Isaiah 7:14 in a scheme where Isaiah is book 27 → `2700701400`

The keys come from versiref (`BibleRef.range_keys`); this package treats them as opaque, comparable integers and never constructs or decodes them.

### Range Overlap Logic

Two verse ranges overlap when:
```
(query_start <= range_end) AND (query_end >= range_start)
```

This allows searching for "Isaiah 7:14" to match documents citing "Isaiah 7:7-16".

## Implementation Status

**Source modules** (under `src/versiref/search/`):
- `models.py`: Core data types (`BlockInfo`, `RawMilestone`, `SearchResult`, `ScopeResult`, analysis results)
- `database.py`: SQLite schema creation and access
- `markdown_parser.py`: Markdown block parsing, frontmatter splitting, milestone extraction
- `indexer.py`: Builds a SQLite index from one or more Markdown files
- `searcher.py`: Queries the index by reference, string, or phrase; retrieves ranges, sections, pages, marginal-number passages, and dated documents
- `analyzer.py`: Reports unrecognized abbreviations and ranks versifications for a source text
- `cli.py`: Click-based CLI entry point
- `__init__.py`: Public API exports

**CLI entry point**: `versiref-search` with subcommands `index`, `analyze`, `search`, `show`, `toc`, `info`, `docs`

**Test modules** (under `tests/`): one per source module, including the CLI

**Not yet implemented**: boolean operators combining reference and string queries (a combined search returns blocks matching either)

## Key Dependencies

- **versiref** (>=0.14.0): For parsing and manipulating Bible references
- **click** (>=8.1.0): CLI framework
- **mistune** (>=3.0.0): Markdown parsing
- **pyyaml** (>=6.0.3): Metadata, config, and frontmatter
- **Python** (>=3.10): Minimum version required
- **SQLite**: Built into Python, used for all indexing

## Design Principles

1. **Portable databases**: Each index is a single SQLite file, built from one document or a collection of them, and regenerated from source rather than migrated
2. **Markdown preservation**: Store and search Markdown as-is to preserve formatting; string search uses FTS5 word-boundary matching with `<mark>` highlight tags in results
3. **Versification scheme awareness**: Each database stores its scheme; all references are scheme-specific
4. **Document order preservation**: Results maintain original document order via sequential IDs
5. **Simple initial implementation**: Command-line tools first, boolean query operators in future phases

## Build System

This project uses `uv_build` as the build backend (specified in pyproject.toml). The module is configured as a namespace package under `versiref.search`.

Key configuration:
- Build backend: `uv_build>=0.13.5,<0.14.0`
- Module name: `versiref.search`
- Package includes a `py.typed` marker for type checking support

## Releasing

When asked to make a release, Claude performs steps 1–8; publishing and pushing are done manually afterward (step 9).

1. Bump the version in `pyproject.toml` (the sole source of the version number).
2. Update `CHANGELOG.md` following the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format: rename the `## Unreleased` heading to the new version with the release date (`## X.Y.Z - YYYY-MM-DD`).
3. Run `uv lock` to update the lock file.
4. Run `pip-audit` (see "Dependency auditing") and verify no unfixed advisories apply.
5. Run tests, type checking, and linting to verify everything passes.
6. Make the release commit (subject line `Release X.Y.Z`).
7. Create an annotated tag named with the bare version number (e.g., `0.5.0`, not `v0.5.0`).
   The tag annotation message is the new version's `CHANGELOG.md` section — its `### Added`/`### Changed`/`### Removed` subsection headings and their entries, but **without** the `## X.Y.Z` version heading line.
   Tag with `git tag -a --cleanup=verbatim -F <file>`: the default cleanup strips lines beginning with `#`, which would silently drop the `###` subsection headings.
   GitHub renders this annotation as the release notes on the releases page.
8. Build the artifacts (Claude builds them but does not publish or push), in order:
   1. Delete any artifacts from previous versions with `rm -f dist/*`, so the directory holds only the current release's files and a publish step that uploads `dist/*` cannot pick up stale builds.
   2. Run `uv build` to produce the wheel and sdist in `dist/`.
9. Manual: publish and push the commit and tag.

## Markdown Style

When writing or editing Markdown documents (docs, README, etc.):
- One sentence per line; do not hard-wrap at a column width.
- Always specify a language on fenced code blocks (e.g., ```yaml, ```python, ```sh).

## Important Files

- `src/versiref/search/docs/`: User-facing documentation, bundled into the package as package data (tracked in git; exposed via the `docs` CLI subcommand)
- `reference/design.md`: Original design document (not tracked in git; may lag the code)
- `uv run versiref docs`: Documentation for the `versiref` dependency
- `pyproject.toml`: Package configuration and dependencies
- `src/versiref/search/__init__.py`: Main package entry point and public API exports
- `uv.lock`: Lock file for reproducible dependency resolution
