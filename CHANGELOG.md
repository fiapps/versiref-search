# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.8.0 - 2026-07-20

### Changed

- Updated `versiref` to 0.10.0, which widens Bible-reference verse keys to carry a subverse ordinal. This lets inserted verses — such as the Greek additions to Esther (ESG 4:17a-z, which follow but are not part of ESG 4:17) — be matched and ordered distinctly from their base verse, while a subverse cited on an ordinary verse still matches that verse.
- Database schema version is now 2.0. Because the change alters how existing verse keys are interpreted, databases built by earlier versions are no longer compatible and must be re-indexed; searching one now fails with a clear "re-index the source document" message instead of silently returning wrong results.

## 0.7.0 - 2026-07-15

### Added

- Page milestones: mark page breaks in the source with `<!-- page: 204 -->` comments (inline or between paragraphs). The markers are stripped from the stored text and indexed separately, so they never disturb search or display. Search results then report the page of each hit (`[Block 42, page 204]`, `page="204"` in XML), and `show --page 204` retrieves the blocks of a printed page. Page numbers may be recorded sparsely; hits then report the most recent recorded page, and looking up an unrecorded page names the recorded pages around it (multi-part values like `2:84` compare part by part, and Roman-numeral front matter sorts before Arabic-numbered pages).
- Commentary scopes: databases can now record which passage a section comments on, as distinct from the passages it cites. `search --commentary -r "John 8:7"` finds the sections commenting on a passage and reports each section's block range for retrieval with `show`. When sections nest, the most specific one is returned, with the enclosing sections visible as heading context. Scopes come from headings that contain a reference (enable with `commentary_headings: true` in the indexing config — for works that are actually commentaries) or from explicit `<!-- scope: John 7:53-8:11 -->` … `<!-- scope: end -->` markers, which also cover works that comment passages out of canonical order.
- `info` and the `index` summary report milestone and commentary-scope counts when present.

### Changed

- Database schema version is now 1.1 (new `milestone` and `commentary_scope` tables). Existing 1.0 databases remain fully searchable — they simply have no pages or scopes until re-indexed.

## 0.6.3 - 2026-07-15

### Changed

- The indexing documentation now describes the optional `description` metadata key and encourages setting it.
- Updated `versiref` to 0.8.0, which adds support for Roman-numeral chapter numbers (common in Latin texts) via the `chapter_number_style` reference-style setting and the new bundled `la-vetus` style.
- The `analyze` command's abbreviation scan now follows the style's chapter-number convention: with a Roman-numeral style it looks for Roman-numeral chapters (accepting both subtractive and additive forms, e.g. `XIV` and `XIIII`, and skipping letter sequences that are not well-formed numerals), and it recognizes abbreviations written with a trailing period (e.g. `Isa.`).

## 0.6.2 - 2026-07-05

### Fixed

- Indexing to an output path that already holds a database now rebuilds it from scratch instead of adding a second copy of every block. Repeatedly re-indexing the same source (for example, while checking a fix) no longer inflates the block and reference counts or produces duplicate search hits. Indexing several input files in one `index` command still combines them into a single database as before.

### Changed

- The indexing documentation now recommends putting `versification` in the config file rather than the metadata file, since it is an indexing parameter and not bibliographic metadata reusable by other outputs, and points to `versiref`'s own bundled docs and its `versiref list versifications` / `versiref list book-names` commands for discovering the available schemes and book-name sets.

## 0.6.1 - 2026-06-30

### Fixed

- References that carry a versification identifier (e.g. "Ps 50:1 Vulg." in a document otherwise cited in English versification) are now indexed at their correct location in the database's versification. Previously such a reference was stored under the raw verse numbering of its own versification, so searching for the equivalent verse in the database's scheme (Ps 51:1) would not find it.

### Changed

- Requires versiref >= 0.6.0, which recognizes trailing versification identifiers when scanning.

## 0.6.0 - 2026-06-29

### Added

- The user documentation (`README`, `indexing`, and `searching`) now ships inside the installed package, so a version-matched copy is available wherever versiref-search is installed, without downloading anything separately.
- `docs` subcommand: prints the filesystem path to the bundled documentation directory, so you can open or `cd` to it from the shell. Pass a file name (e.g. `versiref-search docs searching.md`) to print the path to a single doc instead.

## 0.5.0 - 2026-06-14

### Added

- `show` can now retrieve a whole section at once. Add `--section LEVEL` to pull everything under a heading of that level — a sermon, a chapter of a patristic work, and the like. Point at it with a block it contains (`--start 42 --section 2`) or by its heading text (`--heading "NATIVITY OF THE LORD" --section 2`); add `--end` to span several sections. A section stops at the next heading of the same or a shallower level, so it never spills into the following chapter. To prevent accidentally pulling a whole work, `show` refuses sections larger than `--max-blocks` (default 200) and tells you to raise the limit or pick a deeper level.
- Every command that reads a database (`search`, `show`, `info`, and the table-of-contents reader) now verifies that the file is a versiref-search index before using it. A database from another versiref tool (e.g. versiref-bible), or one built before this check existed, is rejected up front with a clear message telling you to re-index, instead of failing partway through. New indexes carry a `format` marker so they pass the check.

### Changed

- The `context` command is now named `show`. Its existing block-range behaviour (`--start`/`--end`) is unchanged.

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
