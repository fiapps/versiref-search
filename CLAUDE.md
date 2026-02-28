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

### Type Checking
```bash
# Run mypy for type checking
uv run mypy src/
```

### Testing
Tests live in `tests/`. Run with:
```bash
uv run pytest
```

## Architecture

### Core Data Model

The system uses SQLite databases (one per source document) with three main tables:

1. **content**: Stores Markdown blocks in document order
   - `id`: Sequential primary key (determines display order)
   - `block_text`: Markdown text for one block-level element
   - `heading_level`: Integer 1-6 for headings, NULL otherwise

2. **reference_index**: Bible reference positions and ranges
   - `content_id`: References the content block
   - `verse_start`/`verse_end`: 8-digit integer encodings of verse ranges
   - `char_start`/`char_end`: Character positions in block_text
   - Multiple rows per content block if multiple references exist

3. **metadata**: Key-value pairs (title, versification_scheme, lang, author, etc.)

### Verse Encoding

Bible references use 8-digit integers: `BBCCCVVV`
- BB: Book number (01-99) according to versification scheme
- CCC: Chapter number (001-999)
- VVV: Verse number (001-999)

Example: Isaiah 7:14 in a scheme where Isaiah is book 27 → `27007014`

### Range Overlap Logic

Two verse ranges overlap when:
```
(query_start <= range_end) AND (query_end >= range_start)
```

This allows searching for "Isaiah 7:14" to match documents citing "Isaiah 7:7-16".

## Implementation Status

**Current Phase**: Phase 1 complete

**Source modules** (under `src/versiref/search/`):
- `models.py`: Core data types
- `database.py`: SQLite schema creation and access
- `markdown_parser.py`: Markdown block parsing
- `indexer.py`: Builds SQLite index from a Markdown file
- `searcher.py`: Queries the index by reference or string
- `cli.py`: Click-based CLI entry point
- `__init__.py`: Public API exports

**CLI entry point**: `versiref-search` with subcommands `index`, `search`, `context`

**Test modules** (under `tests/`): covers all non-CLI modules

**Implemented Components**:
1. **Indexing module**: `indexer.py` + CLI `index` command — parses Markdown and builds SQLite databases
2. **Search module**: `searcher.py` + CLI `search` and `context` commands — queries databases by reference or string
3. **Python API**: Public interface exported from `__init__.py`

## Key Dependencies

- **versiref** (>=0.3.0): For parsing and manipulating Bible references
- **click** (>=8.1.0): CLI framework
- **mistune** (>=3.0.0): Markdown parsing
- **Python** (>=3.10): Minimum version required
- **SQLite**: Built into Python, used for all indexing

## Design Principles

1. **Per-document databases**: Each source document gets its own SQLite file for portability and easy regeneration
2. **Markdown preservation**: Store and search Markdown as-is to preserve formatting and maintain character position accuracy
3. **Versification scheme awareness**: Each database stores its scheme; all references are scheme-specific
4. **Document order preservation**: Results maintain original document order via sequential IDs
5. **Simple initial implementation**: Command-line tools first, boolean query operators in future phases

## Build System

This project uses `uv_build` as the build backend (specified in pyproject.toml). The module is configured as a namespace package under `versiref.search`.

Key configuration:
- Build backend: `uv_build>=0.9.28,<0.10.0`
- Module name: `versiref.search`
- Package includes a `py.typed` marker for type checking support

## Important Files

- `docs/design.md`: Comprehensive design document with full schema, workflows, and implementation phases
- `docs/versiref/`: Documentation for the `versiref` dependency
- `pyproject.toml`: Package configuration and dependencies
- `src/versiref/search/__init__.py`: Main package entry point and public API exports
- `uv.lock`: Lock file for reproducible dependency resolution
