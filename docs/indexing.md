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

The `versiref.search` package exports `index_document` and `get_index_stats` for programmatic use.
See their docstrings for full parameter documentation.
