# Building Databases

This document covers creating versiref-search databases from Markdown source documents.
If you only need to search existing databases, see [searching.md](searching.md).

> Reference styles, versification schemes, and book-name sets all come from the underlying `versiref` package.
> It ships its own documentation — run `versiref docs` to print the path to it — and offers `versiref list versifications` and `versiref list book-names` to see what is available by name.

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
* lxx                 132    137  96.4%
  vulgata             129    137  94.2%
...

* configured versification (lxx)
```

The leading marker column flags the versification declared in your config (or its metadata file) so you can see at a glance whether your configured choice is also the best fit.
The marker only appears when a config file is supplied.

To act on the report:

- Add the recommended sets to your inline `style:` config block via `also_recognize`, or pick a `--style` whose recognized names already include them.
- Set the top-ranked versification as the `versification` value in your config file (or, if you index without one, in the metadata file).
- Add genuinely-non-Bible abbreviations (e.g., `PL` for *Patrologia Latina*) to `abbreviations_whitelist` so the indexer's abbreviation check stops flagging them.

You can pass the same config file you use for indexing with `-c`/`--config`.
`analyze` reads the `style`, `parser_sensitivity`, and `abbreviations_whitelist` keys, applies the whitelist to suppress non-Bible abbreviations from the report, and flags the configured `versification` in the ranking.
This lets you iterate on a config and confirm it still covers the source — including custom abbreviations defined in an inline `style:` block — before re-running `index`.

If the configured style already recognizes everything, the command prints `All abbreviations are recognized by the configured style.` and proceeds straight to the versification ranking.
If the reference pool is empty (no recognized references at all), the versification ranking is skipped and the command exits with a non-zero status.

### CLI options

```text
versiref-search analyze [OPTIONS] INPUT_FILES...
```

| Option | Description |
|--------|-------------|
| `-c`, `--config` | YAML config file (same format as `index`); supplies `style`, `parser_sensitivity`, `abbreviations_whitelist`, and the marked `versification` |
| `--style` | Named reference style (overrides config; default: `en-cmos_short`) |
| `--sensitivity` | Reference scanner sensitivity: `verse`, `chapter`, or `book` (overrides config; default: `verse`) |

## Metadata File

Every database requires metadata.
The metadata file describes the *work* — title, author, and the like — not how it is indexed.
Keeping indexing parameters out of it means the same metadata file can feed other outputs built from the same source (for example, a Verbum Personal Book).
The file is YAML, optionally wrapped in front-matter delimiters (`---`):

```yaml
---
title: Commentary on Romans
author: J. Smith
lang: en-US
description: Verse-by-verse commentary on Romans; passages are numbered and cross-referenced by the doctrinal index.
---
```

All key-value pairs are stored in the database.
List values are joined with " and " (e.g., multiple authors).

### Required Keys

| Key | Description |
|-----|-------------|
| `title` | Title of the work |

A `versification` is also required, but it is an indexing parameter rather than bibliographic metadata.
When you index with a config file, set it there (see [Config File](#config-file)) and leave it out of the metadata file, so the metadata stays reusable.
Put `versification` in the metadata file only when you index without a config file.
Do not set it in both places.

### Common Optional Keys

These are not enforced but are conventional:

| Key | Description |
|-----|-------------|
| `author` | Author(s) of the work |
| `translator` | Translator(s) |
| `date` | Publication date |
| `lang` | Language code (e.g., `en-US`) |
| `description` | Free-text summary of what the database contains and when to search it |

A `description` is worth adding whenever the `title` alone does not tell a reader — human or LLM — what the database holds or when to reach for it.
Use it to summarize the work's subject and scope, to signal the kinds of questions the database can answer, and to flag anything special that a searcher needs to know about the contents.
For example, note that the text uses numbered passages referenced by a doctrinal index, or that coverage is limited to certain books.
An agent choosing among several databases can read these descriptions to decide which one to search.

## Config File

A config file centralizes indexing options in YAML.
Pass it with `-c`/`--config`.
Here is a full example with all supported keys:

```yaml
# Path to metadata file (resolved relative to config file location)
metadata: metadata.yaml

# Versification scheme for indexing (its preferred home; see Metadata File)
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
This is the preferred place to set the versification, since it is an indexing parameter rather than bibliographic metadata.
If it is also present in the metadata file, the config value wins.
Run `versiref list versifications` to see the available schemes.

#### `style`

Reference style for parsing Bible references in the source text.
Can be either:

- A **named style** string (e.g., `en-cmos_short`, `en-sbl`).
  The default is `en-cmos_short`.
- An **inline style definition** as a YAML mapping with `names`, `chapter_verse_separator`, and optionally `also_recognize`.
  This is useful for texts that use non-standard abbreviations.

Run `versiref list book-names` to see the bundled book-name sets you can draw on for `names` and `also_recognize`.

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
