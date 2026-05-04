# Building Databases

This document covers creating versiref-search databases from Markdown source documents.
If you only need to search existing databases, see [searching.md](searching.md).

## Quick Start

Index a Markdown file into a searchable database:

```sh
versiref-search index chapter1.md -o mybook.db -m metadata.yaml
```

Index multiple files into one database:

```sh
versiref-search index ch1.md ch2.md ch3.md -o mybook.db -m metadata.yaml
```

Use a config file for more control:

```sh
versiref-search index ch1.md ch2.md -o mybook.db -c config.yaml
```

If indexing completes with zero references found, versiref-search will emit a warning.
This usually means the selected style does not match the source text.

## Analyzing a Document Before Indexing

Before committing to a `--style` and a `versification`, run `versiref-search analyze` on the source to see which abbreviations the style covers and which named versification best fits the references in the text.

```sh
versiref-search analyze chapter1.md
```

The command performs two analyses, in order.

**Abbreviation coverage.**
It scans the text with a regex built from the style's chapter/verse separator, then drops anything the style's `recognized_names` already covers.
For whatever is left, it greedy-picks the smallest list of bundled standard-name sets (e.g., `en-sbl_abbreviations`, `en-douay-rheims_names`) that cover the unrecognized names, and reports any leftovers that no bundled set covers.
Candidate sets are scoped to the language prefix of the configured style (e.g., `en-*`); a style whose identifier has no `xx-` or `xxx-` prefix falls back to all bundled sets.
Before the second step, the recommended sets are merged into the style via `also_recognize` so the parser can pick up the previously-unrecognized references.

**Versification ranking.**
With the enriched style in hand, it scans the references and ranks every named versification by the percentage of references that are valid in it (book in the canon, chapter and verse in range).
A higher score suggests the text was authored against that scheme.
Differences typically show up in Psalm numbering and in the inclusion of deuterocanonical books.

Example output:

```text
Analyzed 1 file(s).

Additional book-name sets needed (en-*):
  en-douay-rheims_names
  en-sbl_abbreviations

Names not covered by any set: PL

Reference pool: 137 reference(s).

Versification     Valid  Total  Score
lxx                 132    137  96.4%
vulgata             129    137  94.2%
...
```

To act on the report:

- Add the recommended sets to your inline `style:` config block via `also_recognize`, or pick a `--style` whose recognized names already include them.
- Set the top-ranked versification as the `versification` value in your metadata or config.
- Add genuinely-non-Bible abbreviations (e.g., `PL` for *Patrologia Latina*) to `abbreviations_whitelist` so the indexer's abbreviation check stops flagging them.

If the configured style already recognizes everything, the command prints `All abbreviations are recognized by the configured style.` and proceeds straight to the versification ranking.
If the reference pool is empty (no recognized references at all), the versification ranking is skipped and the command exits with a non-zero status.

### CLI options

```text
versiref-search analyze [OPTIONS] INPUT_FILES...
```

| Option | Description |
|--------|-------------|
| `--style` | Named reference style (default: `en-cmos_short`) |
| `--sensitivity` | Reference scanner sensitivity: `verse`, `chapter`, or `book` (default: `verse`) |

## Metadata File

Every database requires metadata.
At minimum, the metadata must include `title` and `versification`.
The file is YAML, optionally wrapped in front-matter delimiters (`---`):

```yaml
---
title: Commentary on Romans
author: J. Smith
versification: eng
lang: en-US
---
```

All key-value pairs are stored in the database.
List values are joined with " and " (e.g., multiple authors).

### Required Keys

| Key | Description |
|-----|-------------|
| `title` | Title of the work |
| `versification` | Versification scheme (e.g., `eng`, `lxx`, `Vulgata`) |

The `versification` key can alternatively be set in the config file, which takes precedence over the metadata file.

### Common Optional Keys

These are not enforced but are conventional:

| Key | Description |
|-----|-------------|
| `author` | Author(s) of the work |
| `translator` | Translator(s) |
| `date` | Publication date |
| `lang` | Language code (e.g., `en-US`) |

## Config File

A config file centralizes indexing options in YAML.
Pass it with `-c`/`--config`.
Here is a full example with all supported keys:

```yaml
# Path to metadata file (resolved relative to config file location)
metadata: metadata.yaml

# Versification scheme (overrides the one in metadata)
versification: eng

# Reference style: a named style or an inline definition
style: en-cmos_short

# Parser sensitivity for reference scanning
parser_sensitivity: verse

# How to handle invalid references (out-of-range chapter/verse)
invalid_references: warn

# Abbreviations to ignore when checking for unrecognized book names
abbreviations_whitelist:
  - PL
  - SC

# Disable the unrecognized abbreviation check entirely
skip_abbreviations_check: false
```

### Config Key Reference

#### `metadata`

Path to the YAML metadata file.
Resolved relative to the config file's directory.
Can be overridden by the CLI `--metadata` option.

#### `versification`

Versification scheme name (e.g., `eng`, `lxx`, `Vulgata`).
When present, this overrides the `versification` key in the metadata file.

#### `style`

Reference style for parsing Bible references in the source text.
Can be either:

- A **named style** string (e.g., `en-cmos_short`, `en-sbl`).
  The default is `en-cmos_short`.
- An **inline style definition** as a YAML mapping with `names`, `chapter_verse_separator`, and optionally `also_recognize`.
  This is useful for texts that use non-standard abbreviations.

Inline style example:

```yaml
style:
  names:
    GEN: Gen
    PSA: Ps
    MAT: Mt
    # ... (all book IDs you need)
  chapter_verse_separator: ":"
  also_recognize:
    - Acts: ACT
      Rv: REV
```

The CLI `--style` option overrides this (named styles only).

#### `parser_sensitivity`

Controls which references the parser reports.
Default: `verse`.

| Value | Behavior |
|-------|----------|
| `verse` | Only references that specify verse numbers |
| `chapter` | Also includes whole-chapter references (e.g., "Romans 3") |
| `book` | Also includes bare book names (e.g., "Romans") |

Higher sensitivity produces more matches but also more false positives.

#### `invalid_references`

How to handle references with out-of-range chapter or verse numbers (e.g., Psalm 151 in a Protestant versification).
Default: `warn`.

| Value | Behavior |
|-------|----------|
| `warn` | Log a warning and include the reference in the database |
| `exclude` | Log a warning and skip the reference |
| `ignore` | Include silently without warning |

References to books that are not part of the database's versification are always excluded regardless of this setting, because they cannot be represented in the reference index.

#### `abbreviations_whitelist`

A list of abbreviation strings to ignore when checking for unrecognized book names.
Useful when the source text contains abbreviations that look like Bible references but aren't (e.g., `PL` for Patrologia Latina).

#### `skip_abbreviations_check`

Set to `true` to disable the unrecognized abbreviation check entirely.
Default: `false`.
The CLI `--skip-abbreviations-check` flag also disables it.

## CLI Options Reference

```text
versiref-search index [OPTIONS] INPUT_FILES...
```

| Option | Description |
|--------|-------------|
| `-o`, `--output` | Output SQLite database file (required) |
| `-m`, `--metadata` | YAML metadata file (overrides config) |
| `-c`, `--config` | YAML config file |
| `--style` | Named reference style (overrides config) |
| `--skip-abbreviations-check` | Disable abbreviation checking |
| `--whitelist` | Comma-separated abbreviations to ignore (overrides config) |

CLI options take precedence over config file values where both apply.

## Python API

The `versiref.search` package exports the following functions and types for programmatic use:

- `index_document` and `get_index_stats` — build and inspect databases.
- `analyze_documents` — rank named versifications against a set of source files; returns `list[VersificationScore]`.
- `analyze_abbreviations` — find unrecognized book abbreviations and recommend bundled standard-name sets to cover them; returns an `AbbreviationAnalysis`.

See their docstrings for full parameter documentation.
