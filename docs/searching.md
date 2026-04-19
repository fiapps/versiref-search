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

- **Heading context**: the most recent heading at each level preceding the matched block, giving you the section structure.
- **Block text**: the Markdown content of the matched block. Matches are wrapped in `<mark>` tags — matched words for string searches, and cited references for reference searches. When a block is matched by both a string and a reference query, only the string matches are highlighted (see [Highlighting](#highlighting) below).
- **Block ID**: a sequential identifier that can be used with the `context` command to retrieve surrounding content.

### Plain Text Output

The default output shows heading context, a block ID, and the block text.
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
## Chapter Title
### Section Title
<block n="42">
Content of the matched block...
</block>
</result>
</source>
</search-results>
```

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

This is useful for focusing on a particular chapter or section whose block-ID range you already know from a previous search or from the `context` command.

## Highlighting

Both kinds of search wrap their matches in `<mark>` tags in the returned block text.
For string searches, FTS5 highlights the matched words.
For reference searches, the cited reference text itself is highlighted, using the character positions recorded at indexing time.

When a block is matched by both a string query and a reference query in a combined search, only the string-match highlighting is shown for that block; the reference highlighting is suppressed to avoid interleaving two independent sets of `<mark>` tags in the same text.
Blocks that were matched by only one of the two query kinds still get that kind's highlighting.

## Retrieving Context

When a search result looks relevant but you need more surrounding text, use the `context` command with block IDs:

```sh
versiref-search context mybook.db --start 40 --end 45
```

Add `--include-headings` to prepend the heading context for the range.

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
|--------|-------------|
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

## Options Reference

### `search` Command

| Option | Description |
|--------|-------------|
| `-r`, `--reference` | Bible reference to search for |
| `-s`, `--string` | Text string to search for (FTS5 word-boundary, case-insensitive) |
| `--style` | Reference style for query parsing (default: `en-cmos_short`) |
| `-v`, `--versification` | Versification scheme of the query reference (default: `eng`) |
| `--native` | Parse query in each database's native versification |
| `--no-headings` | Omit heading context from results |
| `--xml` | Output in XML format |
| `--start` | Minimum block ID to search (inclusive) |
| `--end` | Maximum block ID to search (inclusive) |

### `context` Command

| Option | Description |
|--------|-------------|
| `--start` | Starting block ID (inclusive) |
| `--end` | Ending block ID (inclusive) |
| `--include-headings` | Include preceding headings before the range |

### `info` Command

Takes one or more database paths as arguments.
No additional options.

## Python API

The `versiref.search` package exports `search_database`, `get_context`, and `get_index_stats` for programmatic use.
See their docstrings for full parameter documentation.
