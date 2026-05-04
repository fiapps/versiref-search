# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
