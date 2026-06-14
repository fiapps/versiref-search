# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Every command that reads a database (`search`, `context`, `info`, and the table-of-contents reader) now verifies that the file is a versiref-search index before using it. A database from another versiref tool (e.g. versiref-bible), or one built before this check existed, is rejected up front with a clear message telling you to re-index, instead of failing partway through. New indexes carry a `format` marker so they pass the check.

## 0.4.1

### Added

- `analyze` subcommand accepts `-c`/`--config FILE`, reusing the same YAML format as `index`. The `style` (named or inline), `parser_sensitivity`, and `abbreviations_whitelist` keys take effect; whitelisted abbreviations no longer surface as "unrecognized" in the report.
- The analyze ranking flags the configured versification (from the config or its linked metadata file) with a leading `*`, so you can see at a glance whether your configured choice is also the best fit.

### Changed

- `analyze` deduplicates references by canonical form before ranking. Spelling variants of the same citation ("Lk 1:28" and "Luke 1:28") and repeated citations of the same verse now contribute one entry to the reference pool rather than several, so ranking percentages reflect the diversity of references in the source rather than how often each one is cited.
- `analyze` is much faster due to the elimination of some unnecessary processing.

## 0.4.0

### Added

- `analyze` subcommand: a preflight tool that scans one or more Markdown files, recommends bundled book-name sets to cover any abbreviations the configured `--style` does not already recognize, and ranks named versifications by how well they fit the references in the text. Documented in `docs/indexing.md`.
- Public Python API: `analyze_documents`, `analyze_abbreviations`, `VersificationScore`, `AbbreviationAnalysis`.

## 0.3.0

### Added

- `toc` subcommand: prints a table of contents of a database's headings. Supports `--depth` (default 2), `--start`/`--end` for block-ID ranges, and `--xml` for machine-readable output.
- `--start` and `--end` options on the `search` command to restrict a search to a range of block IDs.

### Changed

- Search output annotates heading-context lines with their block IDs, matching the form used by `toc`. In plain text, each heading line ends with `{block=N}`; in XML, each heading is wrapped in `<block n="N">...</block>` just like the matched block.

## 0.2.2

### Added

- Reference-search hits are now wrapped in `<mark>` tags in returned block text, using the character spans recorded at indexing time. When a block is matched by both a string and a reference query, string highlighting still wins.

### Changed

- `index` command warns when a source document yields no references.
- Refined the regex used by `find_unrecognized_abbreviations` to reduce false positives.

## 0.2.1

### Added

- `--xml` flag on `search` command for XML-delimited output.
- `parser_sensitivity` config option for controlling versiref parser sensitivity.
- `invalid_references` config option for handling out-of-range references during indexing.
- `--native` flag on `search` command to use the source document's native versification.
- User-facing documentation in `docs/`.

### Changed

- Default search versification is now `eng`.
- Reduced sensitivity of `find_unrecognized_abbreviations` to avoid false positives.

## 0.1.1

### Fixed

- `--version` flag now reports versiref-search version instead of versiref's.

### Changed

- `index` command accepts multiple input files.

## 0.1.0

Initial release.
