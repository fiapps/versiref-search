# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.2.0

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
