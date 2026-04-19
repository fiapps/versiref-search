"""Database schema and operations for versiref-search."""

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

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
    verse_start INTEGER NOT NULL,  -- 8-digit: BBCCCVVV
    verse_end INTEGER NOT NULL,    -- 8-digit: BBCCCVVV
    char_start INTEGER NOT NULL,   -- Character position in block_text
    char_end INTEGER NOT NULL,     -- Character position in block_text
    FOREIGN KEY (content_id) REFERENCES content(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_verse_range ON reference_index(verse_start, verse_end);
CREATE INDEX IF NOT EXISTS idx_content_id ON reference_index(content_id);

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
        """Context manager exit."""
        self.close()

    def connect(self) -> None:
        """Open database connection."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        # Enable foreign key constraints
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
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
        self.conn.commit()

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
        self.conn.commit()
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
            verse_start: Start verse (8-digit integer: BBCCCVVV)
            verse_end: End verse (8-digit integer: BBCCCVVV)
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
        self.conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

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
            query_start: Start of query range (8-digit integer)
            query_end: End of query range (8-digit integer)
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
        """Get the most recent heading at each level before a content block.

        Args:
            content_id: Content block ID to search before

        Returns:
            Dictionary mapping heading_level to (id, block_text)

        """
        if not self.conn:
            raise RuntimeError("Database not connected")

        headings = {}
        for level in range(1, 7):
            heading = self.get_preceding_heading(content_id, level)
            if heading:
                headings[level] = heading
        return headings

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
