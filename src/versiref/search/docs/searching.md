# Searching Databases

versiref-search databases are SQLite files containing indexed Bible references and text content from source documents.
You can search them by Bible reference, by text string, or both.

## Quick Start (CLI)

Search a database for a Bible reference:

```sh
versiref-search search mybook.db -r "Romans 3:23"
```

Search for a text string (or any SQLite FTS5 search expression):

```sh
versiref-search search mybook.db -s "justification"
```

Combine both (results must match both criteria):

```sh
versiref-search search mybook.db -r "Romans 3" -s "faith"
```

Search multiple databases at once:

```sh
versiref-search search book1.db book2.db -r "Ps 23"
```

## Search Results

Results are returned in document order.
Each result includes:

- **Heading context**: the most recent heading at each level preceding the matched block, giving you the section structure. Each heading is tagged with its own block ID so you can jump to it with `show` or narrow a follow-up search with `--start`/`--end`.
- **Block text**: the Markdown content of the matched block. Matches are wrapped in `<mark>` tags — matched words for string searches, and cited references for reference searches. When a block is matched by both a string and a reference query, only the string matches are highlighted (see [Highlighting](#highlighting) below).
- **Block ID**: a sequential identifier that can be used with the `show` command to retrieve surrounding content.
- **Page**: when the database was indexed with page milestones, the page of the printed edition the block falls on (e.g., `[Block 42, page 204]`, or `page="204"` in XML output). With sparse page milestones this is the most recent *recorded* page before the block.

### Plain Text Output

The default output shows heading context, a block ID, and the block text.
Each heading line is annotated with its block ID in braces (the same form used by the `toc` command):

```text
# Chapter Title {block=10}
## Section Title {block=24}

[Block 42]
Content of the matched block...
```

Multiple results are separated by a line of `=` characters.

### XML Output

Use `--xml` for machine-readable output, useful for LLM tool integration:

```sh
versiref-search search mybook.db -r "Ps 23" --xml
```

Output structure:

```xml
<search-results count="2">
<source db="mybook">
<result>
<block n="10">
# Chapter Title
</block>
<block n="24">
## Section Title
</block>
<block n="42">
Content of the matched block...
</block>
</result>
</source>
</search-results>
```

Heading blocks and the matched block use the same `<block n="...">` form — the last `<block>` in each `<result>` is the matched block; any preceding ones are the heading context.

## Reference Search

Reference search finds content blocks that were indexed with overlapping Bible references.
A query for "Isaiah 7:14" will match blocks citing "Isaiah 7:14", "Isaiah 7:7-16", or any range that overlaps with the queried verse(s).

The `--style` option controls how your query reference is parsed.
It defaults to `en-cmos_short` (Chicago Manual of Style short abbreviations).
Other options include `en-sbl` (Society of Biblical Literature).
The style only affects how the *query* is interpreted; it does not need to match the style used when the database was built.

### Versification

Query references are parsed in the `eng` (Protestant English) versification by default and mapped to each database's native scheme automatically.
This means you can search databases that use different versification schemes without thinking about it.

Use `-v` to parse the query in a different scheme:

```sh
versiref-search search mybook.db -r "Ps 22" -v lxx
```

Use `--native` to skip mapping and parse the query directly in each database's own versification:

```sh
versiref-search search mybook.db -r "Ps 23" --native
```

This is useful when you know the database's scheme and want to query in its terms.

## Finding Commentary on a Passage

For databases indexed with commentary scopes (see [indexing.md](indexing.md)), add `--commentary` (`-C`) to a reference search to find the sections that *comment on* a passage, rather than every block that cites it:

```sh
versiref-search search commentary.db -r "John 8:7" --commentary
```

Each result is a section: its heading context, the opening block, and the block range of the whole section, which you can retrieve with `show`:

```text
# Commentary {block=1}
## The Pericope Adulterae (Jn 7:53-8:11) {block=3}

[Blocks 5-6]
### On Jn 8:7
```

When scopes nest — a pericope-level section containing per-verse subsections — only the narrowest matching scope is returned; the enclosing scopes appear as heading context.
A query that overlaps several sibling sections returns each of them.

`--commentary` requires `--reference` and cannot be combined with `--string` or `--start`/`--end`.
The `--style`, `-v`, and `--native` options apply to the query as usual.
In XML output the section is wrapped in `<scope start="..." end="...">` instead of a `<block>` element.

## String Search

String search uses SQLite FTS5 for word-boundary matching.
It is case-insensitive but matches whole words, not substrings.
For example, searching for "grace" will not match "disgrace".

## Limiting the Search Range

Use `--start` and `--end` to restrict a search to a range of block IDs.
Either option may be used on its own; when both are given, `--start` must not exceed `--end`.

```sh
versiref-search search mybook.db -s "faith" --start 40 --end 120
```

This is useful for focusing on a particular chapter or section whose block-ID range you already know from a previous search or from the `show` command.

## Highlighting

Both kinds of search wrap their matches in `<mark>` tags in the returned block text.
For string searches, FTS5 highlights the matched words.
For reference searches, the cited reference text itself is highlighted, using the character positions recorded at indexing time.

When a block is matched by both a string query and a reference query in a combined search, only the string-match highlighting is shown for that block; the reference highlighting is suppressed to avoid interleaving two independent sets of `<mark>` tags in the same text.
Blocks that were matched by only one of the two query kinds still get that kind's highlighting.

## Retrieving Content

When a search result looks relevant but you need more surrounding text, use the `show` command.
In its simplest form it returns an explicit range of block IDs:

```sh
versiref-search show mybook.db --start 40 --end 45
```

Add `--include-headings` to prepend the headings above the range.

### Retrieving a Whole Section

Often the unit you actually want is a whole section — a sermon, a chapter of a patristic work, a homily.
Add `--section LEVEL` to expand the request out to the boundaries of the section at a given heading level (1–6).

Anchor the section either by a block it contains, using `--start`:

```sh
versiref-search show mybook.db --start 42 --section 2
```

This returns every block from the nearest level-2 heading at or before block 42 up to (but not including) the next heading at level 2 or above.
A shallower heading (e.g. a following level-1 chapter) also closes the section, so a section never bleeds into the next chapter.
Add `--end` to span several sections — the result then covers every section touched by the range from `--start` to `--end`.

Or anchor it by the section's heading text, using `--heading`:

```sh
versiref-search show mybook.db --heading "NATIVITY OF THE LORD" --section 2
```

The match is case-insensitive and substring-based.
If more than one level-2 heading matches, `show` lists the candidates with their block IDs so you can re-run with `--start` instead.

As with the range form, `--include-headings` prepends the ancestor headings above the section.

To guard against accidentally pulling a whole work (for example, asking for everything under a level-1 heading), `show` refuses to return a section larger than `--max-blocks` blocks (default 200).
When a section is too large it reports the block count; raise `--max-blocks` or choose a deeper `--section` level.

### Retrieving a Page

For databases indexed with page milestones, `--page` retrieves the blocks of a printed page:

```sh
versiref-search show mybook.db --page 204
```

The result runs from the block where the page begins through the block where the next recorded page begins (blocks holding a mid-paragraph page break belong to both pages).
If the page value is not recorded, the error names the recorded pages around it — useful when page milestones are sparse.
Page values compare naturally for this purpose: multi-part values like `2:84` (volume:page) compare part by part, and Roman-numeral pages (front matter) always sort before Arabic-numbered ones.
With sparse milestones a "page" can span many blocks (everything up to the next recorded break), so the `--max-blocks` guard applies here as it does for sections.
`--page` cannot be combined with the other `show` modes.

## Table of Contents

To survey a database's heading structure, use the `toc` command:

```sh
versiref-search toc mybook.db
```

By default this prints every heading up to level 2.
Each line shows the heading in its original Markdown form, followed by its block ID in braces:

```text
# Book One {block=1}
## Chapter 1 {block=12}
## Chapter 2 {block=87}
```

Use `--depth` to include deeper headings (levels run from 1 to 6), and `--start`/`--end` to restrict to a range of block IDs:

```sh
versiref-search toc mybook.db --depth 3 --start 100 --end 500
```

Use `--xml` for machine-readable output using the same `<block n="...">` form as the `search` command:

```xml
<toc>
<block n="1">
# Book One
</block>
<block n="12">
## Chapter 1
</block>
</toc>
```

### `toc` Command

| Option | Description |
| ------ | ----------- |
| `--depth` | Maximum heading level to include (default: 2) |
| `--start` | Minimum block ID (inclusive) |
| `--end` | Maximum block ID (inclusive) |
| `--xml` | Output in XML format |

## Database Info

To see metadata and statistics for a database:

```sh
versiref-search info mybook.db
```

This shows the title, versification scheme, and other metadata, along with block and reference counts.
Databases with milestones or commentary scopes also report those counts.

## Options Reference

### `search` Command

| Option | Description |
| ------ | ----------- |
| `-r`, `--reference` | Bible reference to search for |
| `-s`, `--string` | Text string to search for (FTS5 word-boundary, case-insensitive) |
| `-C`, `--commentary` | Find commentary on the passage (requires `-r`) |
| `--style` | Reference style for query parsing (default: `en-cmos_short`) |
| `-v`, `--versification` | Versification scheme of the query reference (default: `eng`) |
| `--native` | Parse query in each database's native versification |
| `--no-headings` | Omit heading context from results |
| `--xml` | Output in XML format |
| `--start` | Minimum block ID to search (inclusive) |
| `--end` | Maximum block ID to search (inclusive) |

### `show` Command

| Option | Description |
| ------ | ----------- |
| `--start` | Starting block ID (inclusive); also the anchor block for `--section` |
| `--end` | Ending block ID (inclusive); extends a `--section` request to span sections |
| `--section` | Retrieve a whole section at this heading level (1–6) |
| `--heading` | Select a section by matching its heading text (use with `--section`) |
| `--page` | Retrieve the blocks of a printed page (requires page milestones) |
| `--max-blocks` | Refuse to return a section larger than this many blocks (default: 200) |
| `--include-headings` | Include the headings above the range/section |

### `info` Command

Takes one or more database paths as arguments.
No additional options.

## Python API

The `versiref.search` package exports `search_database`, `search_commentary`, `get_context`, `get_page_context`, `get_section_by_block`, `get_section_by_heading`, and `get_index_stats` for programmatic use.
See their docstrings for full parameter documentation.
