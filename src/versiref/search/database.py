"""Database schema and operations for versiref-search."""

import sqlite3
from pathlib import Path
from typing import Any

from .models import RawMilestone

# Identifies databases produced by this package, distinguishing them from
# other versiref-ecosystem SQLite files (e.g. versiref-bible) that share the
# "schema_version" key. Written to the metadata "format" key at index time.
PRODUCT_NAME = "versiref-search"

# Schema contract version (major.minor), independent of the package version.
# Minor bumps are additive (new tables/columns); a major bump signals a
# breaking change. Code requiring X.Y accepts any database whose major equals
# X and whose minor is >= Y.
#
# A breaking change is not only a change to the table/column structure: it also
# covers a change to how stored values are interpreted. Version 2.0 keeps the
# 1.x table layout but reinterprets the reference/scope verse keys, which
# versiref 0.10.0 widened from 8 digits (BBCCCVVV) to 10 (BBCCCVVVSS, adding a
# subverse ordinal). Old and new keys are different numbers for the same verse,
# so a 1.x database queried by 2.0 code would silently miss — hence the major
# bump, which rejects those databases outright and tells the user to re-index.
#
# SCHEMA_VERSION is what new databases are stamped with at index time;
# REQUIRED_SCHEMA_VERSION is the oldest schema this code can read. They
# differ when new tables are optional at query time (queries against the
# new tables return empty results on older databases).
#
# Version 2.1 adds two conventions to the milestone table, with no change to
# its layout. A milestone of type DOCUMENT_MILESTONE marks the first block of
# each source document, so that page and marg values and heading context stop
# at the document they belong to; and a page or marg milestone whose value is
# MILESTONE_END says that no value is in effect from that point on. A 2.0
# database has neither and is read as before.
SCHEMA_VERSION = "2.1"
REQUIRED_SCHEMA_VERSION = "2.0"

# Milestone type marking the first block of a source document. Its value is
# the document's file name. It cannot be written in a source document, where
# only the types in the milestone comment syntax are recognized.
DOCUMENT_MILESTONE = "document"

# Milestone value ending the run of the previous value of the same type.
MILESTONE_END = "end"


class IncompatibleDatabaseError(Exception):
    """Raised when a database is not a compatible versiref-search index."""


def _parse_schema_version(value: str) -> tuple[int, int]:
    """Parse a ``"major.minor"`` schema version into an ``(int, int)`` tuple.

    Raises:
        ValueError: If the value is not two dot-separated integers.

    """
    parts = value.split(".")
    if len(parts) != 2:
        raise ValueError("expected 'major.minor'")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError("major and minor must be integers")


SCHEMA_SQL = """
-- Stores Markdown blocks in document order
CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    block_text TEXT NOT NULL,
    heading_level INTEGER NULL  -- 1-6 for headings, NULL otherwise
);

-- FTS5 full-text index on content blocks
CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    block_text,
    content='content',
    content_rowid='id'
);

-- Keep FTS5 in sync with the content table
CREATE TRIGGER IF NOT EXISTS content_ai AFTER INSERT ON content BEGIN
    INSERT INTO content_fts(rowid, block_text) VALUES (new.id, new.block_text);
END;
CREATE TRIGGER IF NOT EXISTS content_ad AFTER DELETE ON content BEGIN
    INSERT INTO content_fts(content_fts, rowid, block_text) VALUES('delete', old.id, old.block_text);
END;
CREATE TRIGGER IF NOT EXISTS content_au AFTER UPDATE ON content BEGIN
    INSERT INTO content_fts(content_fts, rowid, block_text) VALUES('delete', old.id, old.block_text);
    INSERT INTO content_fts(rowid, block_text) VALUES (new.id, new.block_text);
END;

-- Indexes Bible reference positions and verse ranges
CREATE TABLE IF NOT EXISTS reference_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL,
    verse_start INTEGER NOT NULL,  -- 10-digit: BBCCCVVVSS
    verse_end INTEGER NOT NULL,    -- 10-digit: BBCCCVVVSS
    char_start INTEGER NOT NULL,   -- Character position in block_text
    char_end INTEGER NOT NULL,     -- Character position in block_text
    FOREIGN KEY (content_id) REFERENCES content(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_verse_range ON reference_index(verse_start, verse_end);
CREATE INDEX IF NOT EXISTS idx_content_id ON reference_index(content_id);

-- Milestones: point markers in the text (page breaks, other locators).
-- Stripped from block_text at index time; char_offset is where the marker
-- fell in the stored (stripped) text.
CREATE TABLE IF NOT EXISTS milestone (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,            -- e.g. 'page'
    value TEXT NOT NULL,           -- e.g. '204', 'xvii'
    content_id INTEGER NOT NULL,
    char_offset INTEGER NOT NULL,  -- position in block_text
    FOREIGN KEY (content_id) REFERENCES content(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_milestone_lookup ON milestone(type, value);
CREATE INDEX IF NOT EXISTS idx_milestone_position ON milestone(type, content_id, char_offset);

-- Commentary scopes: which Scripture passage a span of blocks comments on
-- (as opposed to cites). Block ranges are inclusive and may nest or overlap.
CREATE TABLE IF NOT EXISTS commentary_scope (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    block_start INTEGER NOT NULL,  -- first content id of the commented span
    block_end INTEGER NOT NULL,    -- last content id (inclusive)
    verse_start INTEGER NOT NULL,  -- 10-digit: BBCCCVVVSS
    verse_end INTEGER NOT NULL     -- 10-digit: BBCCCVVVSS
);

CREATE INDEX IF NOT EXISTS idx_scope_verse ON commentary_scope(verse_start, verse_end);

-- Key-value metadata
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    """Manages SQLite database connections and operations."""

    def __init__(self, db_path: str | Path):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file

        """
        self.db_path = Path(db_path)
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> "Database":
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit: keep the writes made, unless an error ended it."""
        if self.conn and exc_type is not None:
            self.conn.rollback()
        self.close()

    def connect(self) -> None:
        """Open database connection."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        # Enable foreign key constraints
        self.conn.execute("PRAGMA foreign_keys = ON")

    def commit(self) -> None:
        """Commit the writes made so far.

        Writes are not committed one by one — doing so makes indexing several
        times slower — but together, here or when the connection closes.
        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        self.conn.commit()

    def close(self) -> None:
        """Commit any pending writes and close the database connection."""
        if self.conn:
            self.conn.commit()
            self.conn.close()
            self.conn = None

    def create_schema(self) -> None:
        """Create database schema if it doesn't exist."""
        if not self.conn:
            raise RuntimeError("Database not connected")

        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def set_metadata(self, key: str, value: str) -> None:
        """Set a metadata key-value pair.

        Args:
            key: Metadata key
            value: Metadata value

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        self.conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value)
        )

    def get_metadata(self, key: str) -> str | None:
        """Get a metadata value by key.

        Args:
            key: Metadata key

        Returns:
            Metadata value or None if not found

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else None

    def get_all_metadata(self) -> dict[str, str]:
        """Get all metadata as a dictionary.

        Returns:
            Dictionary of metadata key-value pairs

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute("SELECT key, value FROM metadata")
        return {row["key"]: row["value"] for row in cursor.fetchall()}

    def validate_schema(self) -> None:
        """Verify this database is a compatible versiref-search index.

        Checks the product identity marker first (so that another
        versiref-ecosystem database is rejected cleanly rather than failing
        later on a missing table), then the schema version using the additive
        rule: the database's major version must equal this code's major
        version, and its minor version must be >= this code's minimum minor
        version (:data:`REQUIRED_SCHEMA_VERSION`).

        Raises:
            IncompatibleDatabaseError: If the database lacks the product
                marker (legacy/unmarked — re-index to fix), declares a
                different product, or has an incompatible schema version.

        """
        product = self.get_metadata("format")
        if product is None:
            raise IncompatibleDatabaseError(
                f"{self.db_path}: not a versiref-search database "
                "(missing 'format' marker); re-index the source document"
            )
        if product != PRODUCT_NAME:
            raise IncompatibleDatabaseError(
                f"{self.db_path}: database format is '{product}', not '{PRODUCT_NAME}'"
            )

        version = self.get_metadata("schema_version")
        if version is None:
            raise IncompatibleDatabaseError(
                f"{self.db_path}: missing schema_version metadata"
            )
        try:
            db_major, db_minor = _parse_schema_version(version)
        except ValueError as e:
            raise IncompatibleDatabaseError(
                f"{self.db_path}: unparseable schema_version '{version}': {e}"
            )

        req_major, req_minor = _parse_schema_version(REQUIRED_SCHEMA_VERSION)
        if db_major != req_major or db_minor < req_minor:
            raise IncompatibleDatabaseError(
                f"{self.db_path}: schema version {version} is incompatible with "
                f"this code (requires {REQUIRED_SCHEMA_VERSION}); "
                "re-index the source document"
            )

    def insert_content(self, block_text: str, heading_level: int | None = None) -> int:
        """Insert a content block.

        Args:
            block_text: Markdown text for the block
            heading_level: Heading level (1-6) or None for non-headings

        Returns:
            ID of inserted content block

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            "INSERT INTO content (block_text, heading_level) VALUES (?, ?)",
            (block_text, heading_level),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def insert_reference(
        self,
        content_id: int,
        verse_start: int,
        verse_end: int,
        char_start: int,
        char_end: int,
    ) -> int:
        """Insert a Bible reference index entry.

        Args:
            content_id: ID of content block containing the reference
            verse_start: Start verse (10-digit integer: BBCCCVVVSS)
            verse_end: End verse (10-digit integer: BBCCCVVVSS)
            char_start: Character position in block_text where reference starts
            char_end: Character position in block_text where reference ends

        Returns:
            ID of inserted reference index entry

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            """INSERT INTO reference_index
               (content_id, verse_start, verse_end, char_start, char_end)
               VALUES (?, ?, ?, ?, ?)""",
            (content_id, verse_start, verse_end, char_start, char_end),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def _table_exists(self, name: str) -> bool:
        """Return True if a table exists in this database.

        Used to degrade gracefully on databases created before a table was
        added to the schema (schema 1.0 lacks milestone/commentary_scope).
        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        )
        return cursor.fetchone() is not None

    def insert_milestone(
        self, type: str, value: str, content_id: int, char_offset: int
    ) -> int:
        """Insert a milestone marker.

        Args:
            type: Milestone type (e.g., "page")
            value: Milestone value (e.g., "204", "xvii")
            content_id: ID of content block the milestone falls in
            char_offset: Character position in block_text where it falls

        Returns:
            ID of inserted milestone

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            """INSERT INTO milestone (type, value, content_id, char_offset)
               VALUES (?, ?, ?, ?)""",
            (type, value, content_id, char_offset),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def get_milestone_for_block(
        self, content_id: int, milestone_type: str, char_offset: int = 0
    ) -> str | None:
        """Get the milestone value in effect at a position, if any exist.

        Returns the value of the latest milestone of the given type at or
        before the given position. With sparse milestones this is the most
        recent *recorded* value, which may precede the actual position (e.g.
        the actual printed page, or the actual marginal-number passage).

        Args:
            content_id: Content block ID
            milestone_type: Milestone type to look up (e.g. "page", "marg")
            char_offset: Character position within the block (default: block
                start, which still counts milestones recorded at offset 0)

        Only milestones of the block's own document count, and an end marker
        (:data:`MILESTONE_END`) leaves no value in effect.

        Returns:
            Milestone value, or None if no milestone of this type is in
            effect at the position (including databases without a milestone
            table).

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return None

        cursor = self.conn.execute(
            """SELECT value FROM milestone
               WHERE type = ?
                 AND content_id >= ?
                 AND (content_id < ? OR (content_id = ? AND char_offset <= ?))
               ORDER BY content_id DESC, char_offset DESC
               LIMIT 1""",
            (
                milestone_type,
                self.get_document_start(content_id) or 0,
                content_id,
                content_id,
                char_offset,
            ),
        )
        row = cursor.fetchone()
        if row is None or row["value"] == MILESTONE_END:
            return None
        value: str = row["value"]
        return value

    def get_document_start(self, content_id: int) -> int | None:
        """Get the first block of the source document a block belongs to.

        Args:
            content_id: Content block ID

        Returns:
            Content ID of the document's first block, or None if the database
            records no document boundary at or before the block (as in one
            indexed before boundaries were recorded).

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return None

        cursor = self.conn.execute(
            "SELECT MAX(content_id) AS id FROM milestone "
            "WHERE type = ? AND content_id <= ?",
            (DOCUMENT_MILESTONE, content_id),
        )
        start: int | None = cursor.fetchone()["id"]
        return start

    def get_next_document_start(self, content_id: int) -> int | None:
        """Get the first block of the next source document after a block.

        Args:
            content_id: Content block ID

        Returns:
            Content ID of the first block of the following document, or None
            if the block is in the last (or only) document.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return None

        cursor = self.conn.execute(
            "SELECT MIN(content_id) AS id FROM milestone "
            "WHERE type = ? AND content_id > ?",
            (DOCUMENT_MILESTONE, content_id),
        )
        start: int | None = cursor.fetchone()["id"]
        return start

    def get_document_name(self, content_id: int) -> str | None:
        """Get the file name of the source document a block belongs to.

        Args:
            content_id: Content block ID

        Returns:
            The document's file name, or None if the database records no
            document boundary at or before the block.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return None

        cursor = self.conn.execute(
            """SELECT value FROM milestone
               WHERE type = ? AND content_id <= ?
               ORDER BY content_id DESC
               LIMIT 1""",
            (DOCUMENT_MILESTONE, content_id),
        )
        row = cursor.fetchone()
        return row["value"] if row else None

    def get_milestones_in_range(
        self, start_id: int, end_id: int, types: tuple[str, ...] = ("page", "marg")
    ) -> dict[int, list[RawMilestone]]:
        """Get the milestones falling inside a range of content blocks.

        Unlike :meth:`get_milestone_for_block`, which reports the value in
        effect at a position, this reports the markers themselves — including
        those that fall mid-block, where the value in effect changes partway
        through the text.

        Args:
            start_id: First content block ID (inclusive)
            end_id: Last content block ID (inclusive)
            types: Milestone types to include

        Returns:
            Mapping of content ID to its milestones in document order. Blocks
            with no milestones are absent; empty on databases without a
            milestone table.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return {}

        placeholders = ", ".join("?" for _ in types)
        cursor = self.conn.execute(
            f"""SELECT type, value, content_id, char_offset FROM milestone
                WHERE type IN ({placeholders})
                  AND content_id BETWEEN ? AND ?
                ORDER BY content_id, char_offset""",
            (*types, start_id, end_id),
        )
        milestones: dict[int, list[RawMilestone]] = {}
        for row in cursor.fetchall():
            milestones.setdefault(row["content_id"], []).append(
                RawMilestone(
                    type=row["type"], value=row["value"], offset=row["char_offset"]
                )
            )
        return milestones

    def get_last_milestone_in_range(
        self, milestone_type: str, start_id: int, end_id: int
    ) -> str | None:
        """Get the value of the last milestone of a type inside a block range.

        Args:
            milestone_type: Milestone type to look up (e.g. "page", "marg")
            start_id: First content block ID (inclusive)
            end_id: Last content block ID (inclusive)

        End markers are passed over: the result is the last real value.

        Returns:
            Milestone value, or None if the range holds no milestone of this
            type (including databases without a milestone table).

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return None

        cursor = self.conn.execute(
            """SELECT value FROM milestone
               WHERE type = ? AND value != ? AND content_id BETWEEN ? AND ?
               ORDER BY content_id DESC, char_offset DESC
               LIMIT 1""",
            (milestone_type, MILESTONE_END, start_id, end_id),
        )
        row = cursor.fetchone()
        return row["value"] if row else None

    def find_milestone_blocks(self, milestone_type: str, value: str) -> list[int]:
        """Get the blocks in which a milestone value is recorded.

        A value is normally recorded once, but a database built from several
        documents may hold the same page number in each.

        Args:
            milestone_type: Milestone type to look up (e.g. "page", "marg")
            value: Milestone value to look up (exact match)

        Returns:
            Content IDs holding a milestone with this value, in document
            order. Empty on databases without a milestone table.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return []

        cursor = self.conn.execute(
            """SELECT DISTINCT content_id FROM milestone
               WHERE type = ? AND value = ?
               ORDER BY content_id""",
            (milestone_type, value),
        )
        return [row["content_id"] for row in cursor.fetchall()]

    def get_milestone_range(
        self, milestone_type: str, value: str, from_block: int | None = None
    ) -> tuple[int, int] | None:
        """Get the content-block span covered by a milestone value.

        The span runs from the block holding the milestone through the block
        holding the next milestone of the same type (inclusive, since a
        marker can fall mid-block) — an end marker counts as one — or through
        the last block of the milestone's document if no other follows in it.

        Args:
            milestone_type: Milestone type to look up (e.g. "page", "marg")
            value: Milestone value to look up (exact match)
            from_block: Take the first milestone with this value at or after
                this content ID, rather than the first in the database

        Returns:
            Tuple of (start_id, end_id), or None if no such milestone
            (including databases without a milestone table).

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return None

        cursor = self.conn.execute(
            """SELECT content_id, char_offset FROM milestone
               WHERE type = ? AND value = ? AND content_id >= ?
               ORDER BY content_id, char_offset
               LIMIT 1""",
            (milestone_type, value, from_block or 0),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        start_id, start_offset = row["content_id"], row["char_offset"]

        max_id = self.get_max_content_id()
        assert max_id is not None  # a milestone implies at least one block
        end_id: int = max_id

        next_document = self.get_next_document_start(start_id)
        if next_document is not None:
            end_id = next_document - 1

        cursor = self.conn.execute(
            """SELECT content_id FROM milestone
               WHERE type = ?
                 AND (content_id > ? OR (content_id = ? AND char_offset > ?))
               ORDER BY content_id, char_offset
               LIMIT 1""",
            (milestone_type, start_id, start_id, start_offset),
        )
        row = cursor.fetchone()
        if row is not None:
            end_id = min(end_id, row["content_id"])

        return start_id, end_id

    def get_milestone_values(self, milestone_type: str) -> list[str]:
        """Get all milestone values of a type, in document order.

        Args:
            milestone_type: Milestone type to look up (e.g. "page", "marg")

        Returns:
            List of values in document order, without end markers. Empty on
            databases without a milestone table.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return []

        cursor = self.conn.execute(
            """SELECT value FROM milestone
               WHERE type = ? AND value != ?
               ORDER BY content_id, char_offset""",
            (milestone_type, MILESTONE_END),
        )
        return [row["value"] for row in cursor.fetchall()]

    def insert_scope(
        self, block_start: int, block_end: int, verse_start: int, verse_end: int
    ) -> int:
        """Insert a commentary scope entry.

        Args:
            block_start: First content ID of the commented span
            block_end: Last content ID of the commented span (inclusive)
            verse_start: Start verse (10-digit integer: BBCCCVVVSS)
            verse_end: End verse (10-digit integer: BBCCCVVVSS)

        Returns:
            ID of inserted scope entry

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            """INSERT INTO commentary_scope
               (block_start, block_end, verse_start, verse_end)
               VALUES (?, ?, ?, ?)""",
            (block_start, block_end, verse_start, verse_end),
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def search_scopes(
        self, query_start: int, query_end: int
    ) -> list[tuple[int, int, int, int, int]]:
        """Search for commentary scopes whose verse range overlaps the query range.

        Args:
            query_start: Start of query range (10-digit integer)
            query_end: End of query range (10-digit integer)

        Returns:
            List of tuples: (id, block_start, block_end, verse_start,
            verse_end), ordered by block_start then block_end. Empty on
            databases without a commentary_scope table.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("commentary_scope"):
            return []

        cursor = self.conn.execute(
            """SELECT id, block_start, block_end, verse_start, verse_end
               FROM commentary_scope
               WHERE verse_start <= ? AND verse_end >= ?
               ORDER BY block_start, block_end""",
            (query_end, query_start),
        )
        return [
            (
                row["id"],
                row["block_start"],
                row["block_end"],
                row["verse_start"],
                row["verse_end"],
            )
            for row in cursor.fetchall()
        ]

    def search_by_reference_range(
        self,
        query_start: int,
        query_end: int,
        block_start: int | None = None,
        block_end: int | None = None,
    ) -> list[tuple[int, str, int, int]]:
        """Search for reference spans whose stored range overlaps the query range.

        Returns one row per matching reference_index entry, so a content block
        with multiple matching references appears multiple times — callers that
        want to highlight every match need all spans.

        Args:
            query_start: Start of query range (10-digit integer)
            query_end: End of query range (10-digit integer)
            block_start: Optional minimum content block ID (inclusive)
            block_end: Optional maximum content block ID (inclusive)

        Returns:
            List of tuples: (content_id, block_text, char_start, char_end),
            ordered by content_id then char_start.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        sql = [
            "SELECT c.id, c.block_text, r.char_start, r.char_end",
            "FROM content c",
            "JOIN reference_index r ON r.content_id = c.id",
            "WHERE r.verse_start <= ? AND r.verse_end >= ?",
        ]
        params: list[Any] = [query_end, query_start]
        if block_start is not None:
            sql.append("AND c.id >= ?")
            params.append(block_start)
        if block_end is not None:
            sql.append("AND c.id <= ?")
            params.append(block_end)
        sql.append("ORDER BY c.id, r.char_start")

        cursor = self.conn.execute("\n".join(sql), params)
        return [
            (row["id"], row["block_text"], row["char_start"], row["char_end"])
            for row in cursor.fetchall()
        ]

    def search_by_string(
        self,
        search_term: str,
        block_start: int | None = None,
        block_end: int | None = None,
    ) -> list[tuple[int, str]]:
        """Search for content blocks containing a word/phrase (FTS5 word-boundary matching).

        Args:
            search_term: Text to search for
            block_start: Optional minimum content block ID (inclusive)
            block_end: Optional maximum content block ID (inclusive)

        Returns:
            List of tuples: (content_id, highlighted_block_text) where
            highlighted_block_text contains <mark>...</mark> around matches

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        sql = [
            "SELECT rowid, highlight(content_fts, 0, '<mark>', '</mark>')",
            "FROM content_fts",
            "WHERE content_fts MATCH ?",
        ]
        params: list[Any] = [search_term]
        if block_start is not None:
            sql.append("AND rowid >= ?")
            params.append(block_start)
        if block_end is not None:
            sql.append("AND rowid <= ?")
            params.append(block_end)
        sql.append("ORDER BY rowid")

        cursor = self.conn.execute("\n".join(sql), params)
        return [(row[0], row[1]) for row in cursor.fetchall()]

    def get_content_by_id(self, content_id: int) -> tuple[int, str, int | None] | None:
        """Get a content block by ID.

        Args:
            content_id: Content block ID

        Returns:
            Tuple of (id, block_text, heading_level) or None if not found

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            "SELECT id, block_text, heading_level FROM content WHERE id = ?",
            (content_id,),
        )
        row = cursor.fetchone()
        return (row["id"], row["block_text"], row["heading_level"]) if row else None

    def get_content_range(
        self, start_id: int, end_id: int
    ) -> list[tuple[int, str, int | None]]:
        """Get a range of content blocks.

        Args:
            start_id: Starting content ID (inclusive)
            end_id: Ending content ID (inclusive)

        Returns:
            List of tuples: (id, block_text, heading_level)

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            """SELECT id, block_text, heading_level
               FROM content
               WHERE id >= ? AND id <= ?
               ORDER BY id""",
            (start_id, end_id),
        )
        return [
            (row["id"], row["block_text"], row["heading_level"])
            for row in cursor.fetchall()
        ]

    def get_headings(
        self,
        max_level: int,
        block_start: int | None = None,
        block_end: int | None = None,
    ) -> list[tuple[int, str, int]]:
        """Get all heading blocks at or above a given level, in document order.

        Args:
            max_level: Include headings with level <= this value (e.g., 2 returns h1 and h2)
            block_start: Optional minimum content block ID (inclusive)
            block_end: Optional maximum content block ID (inclusive)

        Returns:
            List of tuples: (id, block_text, heading_level), in document order

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        sql = [
            "SELECT id, block_text, heading_level",
            "FROM content",
            "WHERE heading_level IS NOT NULL AND heading_level <= ?",
        ]
        params: list[Any] = [max_level]
        if block_start is not None:
            sql.append("AND id >= ?")
            params.append(block_start)
        if block_end is not None:
            sql.append("AND id <= ?")
            params.append(block_end)
        sql.append("ORDER BY id")

        cursor = self.conn.execute("\n".join(sql), params)
        return [
            (row["id"], row["block_text"], row["heading_level"])
            for row in cursor.fetchall()
        ]

    def get_preceding_heading(
        self, content_id: int, heading_level: int
    ) -> tuple[int, str] | None:
        """Get the most recent heading at a specific level before a content block.

        Args:
            content_id: Content block ID to search before
            heading_level: Heading level to search for (1-6)

        Returns:
            Tuple of (id, block_text) or None if not found

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            """SELECT id, block_text
               FROM content
               WHERE id < ? AND heading_level = ?
               ORDER BY id DESC
               LIMIT 1""",
            (content_id, heading_level),
        )
        row = cursor.fetchone()
        return (row["id"], row["block_text"]) if row else None

    def get_all_preceding_headings(self, content_id: int) -> dict[int, tuple[int, str]]:
        """Get the chain of headings enclosing a content block.

        Walks backwards from the block: the nearest preceding heading is its
        immediate parent, and each further step looks only for a heading
        strictly shallower than the one already found. A heading at level N
        therefore closes every open heading at level >= N, and the returned
        chain always has increasing levels and increasing block IDs. The walk
        stops at the start of the block's own document, so the headings of an
        earlier document in the same database never enclose it.

        Args:
            content_id: Content block ID to search before

        Returns:
            Dictionary mapping heading_level to (id, block_text)

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        headings: dict[int, tuple[int, str]] = {}
        document_start = self.get_document_start(content_id) or 0
        before_id = content_id - 1
        max_level = 6
        while max_level >= 1:
            heading = self.get_enclosing_heading(
                before_id, max_level, min_id=document_start
            )
            if heading is None:
                break
            heading_id, heading_text, level = heading
            headings[level] = (heading_id, heading_text)
            before_id = heading_id - 1
            max_level = level - 1
        return headings

    def get_enclosing_heading(
        self, block_id: int, max_level: int, min_id: int = 0
    ) -> tuple[int, str, int] | None:
        """Get the nearest heading at or above a level that precedes a block.

        Returns the most recent heading whose level is <= ``max_level`` and
        whose ID is <= ``block_id``. This is the heading that opens the section
        the block belongs to (when its level equals ``max_level``); a shallower
        level means the block is not inside a section at the requested level.

        Args:
            block_id: Content block ID (inclusive — a heading at this ID counts)
            max_level: Highest (shallowest) heading level to consider
            min_id: Earliest content ID to consider (inclusive), for keeping
                the search inside one document

        Returns:
            Tuple of (id, block_text, heading_level), or None if no qualifying
            heading precedes the block.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            """SELECT id, block_text, heading_level
               FROM content
               WHERE id <= ? AND id >= ?
                 AND heading_level IS NOT NULL AND heading_level <= ?
               ORDER BY id DESC
               LIMIT 1""",
            (block_id, min_id, max_level),
        )
        row = cursor.fetchone()
        return (row["id"], row["block_text"], row["heading_level"]) if row else None

    def get_next_heading_id(self, block_id: int, max_level: int) -> int | None:
        """Get the ID of the next heading at or above a level after a block.

        Returns the smallest content ID greater than ``block_id`` whose heading
        level is <= ``max_level``. This marks where the current section ends: a
        heading of the same level starts a sibling section, and a shallower
        heading closes the enclosing one.

        Args:
            block_id: Content block ID to search after (exclusive)
            max_level: Highest (shallowest) heading level to consider

        Returns:
            The next heading's content ID, or None if none follows.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            """SELECT id
               FROM content
               WHERE id > ? AND heading_level IS NOT NULL AND heading_level <= ?
               ORDER BY id ASC
               LIMIT 1""",
            (block_id, max_level),
        )
        row = cursor.fetchone()
        return row["id"] if row else None

    def find_headings_by_text(self, text: str, level: int) -> list[tuple[int, str]]:
        """Find headings at a level whose text contains a substring.

        Matching is case-insensitive and substring-based, against the stored
        heading text (which includes the leading ``#`` markers).

        Args:
            text: Substring to look for
            level: Exact heading level to match

        Returns:
            List of (id, block_text) tuples in document order.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            "SELECT id, block_text FROM content WHERE heading_level = ? ORDER BY id",
            (level,),
        )
        needle = text.lower()
        return [
            (row["id"], row["block_text"])
            for row in cursor.fetchall()
            if needle in row["block_text"].lower()
        ]

    def get_max_content_id(self) -> int | None:
        """Get the highest content block ID, or None if the table is empty."""
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute("SELECT MAX(id) AS max_id FROM content")
        return cursor.fetchone()["max_id"]

    def count_content_range(self, start_id: int, end_id: int) -> int:
        """Count content blocks with ID in ``[start_id, end_id]`` (inclusive)."""
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute(
            "SELECT COUNT(*) AS count FROM content WHERE id >= ? AND id <= ?",
            (start_id, end_id),
        )
        return cursor.fetchone()["count"]

    def count_content_blocks(self) -> int:
        """Count total number of content blocks.

        Returns:
            Number of content blocks

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute("SELECT COUNT(*) as count FROM content")
        row = cursor.fetchone()
        return row["count"]

    def count_references(self) -> int:
        """Count total number of reference index entries.

        Returns:
            Number of reference index entries

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        cursor = self.conn.execute("SELECT COUNT(*) as count FROM reference_index")
        row = cursor.fetchone()
        return row["count"]

    def count_milestones(self) -> int:
        """Count milestone entries (0 on databases without the table).

        Document boundaries share the table but are not counted: they are
        recorded by the indexer, not written in the source.
        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return 0

        cursor = self.conn.execute(
            "SELECT COUNT(*) as count FROM milestone WHERE type != ?",
            (DOCUMENT_MILESTONE,),
        )
        return cursor.fetchone()["count"]

    def count_milestones_by_type(self) -> dict[str, int]:
        """Count the values recorded for each milestone type.

        Returns:
            Mapping of milestone type (e.g. "page", "marg") to the number of
            values recorded, for the types the database has any of. Document
            boundaries and end markers are not values and are left out. Empty
            on databases without a milestone table.

        """
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("milestone"):
            return {}

        cursor = self.conn.execute(
            """SELECT type, COUNT(*) AS count FROM milestone
               WHERE type != ? AND value != ?
               GROUP BY type
               ORDER BY type""",
            (DOCUMENT_MILESTONE, MILESTONE_END),
        )
        return {row["type"]: row["count"] for row in cursor.fetchall()}

    def count_scopes(self) -> int:
        """Count commentary scope entries (0 on databases without the table)."""
        if not self.conn:
            raise RuntimeError("Database not connected")
        if not self._table_exists("commentary_scope"):
            return 0

        cursor = self.conn.execute("SELECT COUNT(*) as count FROM commentary_scope")
        return cursor.fetchone()["count"]
