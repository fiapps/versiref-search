"""Tests for the indexer module."""

import logging
import pytest
from pathlib import Path

from versiref import RefStyle, standard_names
from versiref.search import (
    index_document,
    get_index_stats,
    find_unrecognized_abbreviations,
)
from versiref.search import IncompatibleDatabaseError
from versiref.search.database import Database, SCHEMA_VERSION

SAMPLE_MD = Path(__file__).parent / "data" / "irenaeus-ah-3.21.md"


def test_missing_input_raises(tmp_path, ref_style):
    with pytest.raises(FileNotFoundError):
        index_document(
            input_path=tmp_path / "nonexistent.md",
            output_path=tmp_path / "out.db",
            metadata={"title": "Test", "versification": "eng"},
            ref_style=ref_style,
        )


def test_invalid_versification_raises(tmp_path, minimal_md, ref_style):
    with pytest.raises(ValueError, match="versification"):
        index_document(
            input_path=minimal_md,
            output_path=tmp_path / "out.db",
            metadata={"title": "Test", "versification": "not_a_real_scheme"},
            ref_style=ref_style,
        )


def test_creates_database_file(tmp_path, minimal_md, ref_style):
    db_path = tmp_path / "out.db"
    assert not db_path.exists()
    index_document(
        input_path=minimal_md,
        output_path=db_path,
        metadata={"title": "Test", "versification": "eng"},
        ref_style=ref_style,
    )
    assert db_path.exists()


def test_reindex_replaces_by_default(tmp_path, minimal_md, ref_style):
    db_path = tmp_path / "out.db"
    meta = {"title": "Test", "versification": "eng"}
    index_document(minimal_md, db_path, meta, ref_style)
    first = get_index_stats(db_path)
    # Re-indexing the same source must not accumulate duplicate blocks.
    index_document(minimal_md, db_path, meta, ref_style)
    second = get_index_stats(db_path)
    assert second["block_count"] == first["block_count"]
    assert second["reference_count"] == first["reference_count"]


def test_append_accumulates(tmp_path, minimal_md, ref_style):
    db_path = tmp_path / "out.db"
    meta = {"title": "Test", "versification": "eng"}
    index_document(minimal_md, db_path, meta, ref_style)
    first = get_index_stats(db_path)
    index_document(minimal_md, db_path, meta, ref_style, append=True)
    second = get_index_stats(db_path)
    assert second["block_count"] == 2 * first["block_count"]
    assert second["reference_count"] == 2 * first["reference_count"]


def test_failed_reindex_leaves_existing_db_intact(tmp_path, minimal_md, ref_style):
    db_path = tmp_path / "out.db"
    meta = {"title": "Test", "versification": "eng"}
    index_document(minimal_md, db_path, meta, ref_style)
    before = get_index_stats(db_path)
    # A call that fails validation must not delete the good database.
    with pytest.raises(ValueError):
        index_document(
            minimal_md, db_path, {"title": "Bad", "versification": "nope"}, ref_style
        )
    after = get_index_stats(db_path)
    assert after["block_count"] == before["block_count"]


def test_block_count(indexed_db):
    stats = get_index_stats(indexed_db)
    # minimal_md: h1, paragraph(Lk 1:28), h2, paragraph(Ps 45:10), paragraph = 5
    assert stats["block_count"] == 5


def test_reference_count(indexed_db):
    stats = get_index_stats(indexed_db)
    # minimal_md has Lk 1:28 and Ps 45:10 — one entry each
    assert stats["reference_count"] == 2


def test_metadata_stored(indexed_db):
    meta = get_index_stats(indexed_db)["metadata"]
    assert meta["title"] == "Test Document"
    assert meta["versification_scheme"] == "eng"
    assert meta["lang"] == "en"
    assert meta["author"] == "Test Author"
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["format"] == "versiref-search"


def test_stats_rejects_unmarked_db(tmp_path):
    path = tmp_path / "unmarked.db"
    with Database(path) as db:
        db.create_schema()
        db.set_metadata("schema_version", "1.0")
    with pytest.raises(IncompatibleDatabaseError, match="format"):
        get_index_stats(path)


def test_author_omitted_when_not_provided(tmp_path, minimal_md, ref_style):
    db_path = tmp_path / "out.db"
    index_document(
        input_path=minimal_md,
        output_path=db_path,
        metadata={"title": "No Author", "versification": "eng"},
        ref_style=ref_style,
    )
    meta = get_index_stats(db_path)["metadata"]
    assert "author" not in meta


def test_get_index_stats_missing_db(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_index_stats(tmp_path / "nonexistent.db")


def test_list_metadata_joined(tmp_path, minimal_md, ref_style):
    db_path = tmp_path / "out.db"
    index_document(
        input_path=minimal_md,
        output_path=db_path,
        metadata={
            "title": "Test",
            "versification": "eng",
            "author": ["Alice", "Bob"],
        },
        ref_style=ref_style,
    )
    meta = get_index_stats(db_path)["metadata"]
    assert meta["author"] == "Alice and Bob"


def test_extra_metadata_stored(tmp_path, minimal_md, ref_style):
    db_path = tmp_path / "out.db"
    index_document(
        input_path=minimal_md,
        output_path=db_path,
        metadata={
            "title": "Test",
            "versification": "eng",
            "translator": ["Paul Spilsbury"],
            "date": 2006,
        },
        ref_style=ref_style,
    )
    meta = get_index_stats(db_path)["metadata"]
    assert meta["translator"] == "Paul Spilsbury"
    assert meta["date"] == "2006"


def test_missing_required_metadata_raises(tmp_path, minimal_md, ref_style):
    with pytest.raises(ValueError, match="title"):
        index_document(
            input_path=minimal_md,
            output_path=tmp_path / "out.db",
            metadata={"versification": "eng"},
            ref_style=ref_style,
        )


def test_sample_file_block_and_reference_counts(tmp_path, ref_style):
    """Integration test: index the actual sample file and verify known counts."""
    db_path = tmp_path / "irenaeus.db"
    index_document(
        input_path=SAMPLE_MD,
        output_path=db_path,
        metadata={"title": "Irenaeus AH 3.21", "versification": "eng"},
        ref_style=ref_style,
    )
    stats = get_index_stats(db_path)
    assert stats["block_count"] == 13
    assert stats["reference_count"] == 5


# --- Tests for find_unrecognized_abbreviations ---


class TestFindUnrecognizedAbbreviations:
    def test_unrecognized_abbreviation_warns(self, ref_style, caplog):
        text = "See PL 39:243 for details."
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            result = find_unrecognized_abbreviations(text, ref_style)
        assert "PL" in result
        assert 'Unrecognized abbreviation "PL"' in caplog.text

    def test_whitelist_suppresses_warning(self, ref_style, caplog):
        text = "See PL 39:243 for details."
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            result = find_unrecognized_abbreviations(text, ref_style, whitelist=["PL"])
        assert result == {}
        assert "PL" not in caplog.text

    def test_recognized_abbreviation_no_warning(self, ref_style, caplog):
        text = "See Gn 1:1 for the beginning."
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            result = find_unrecognized_abbreviations(text, ref_style)
        assert result == {}
        assert caplog.text == ""

    def test_numbered_book_abbreviation(self, ref_style, caplog):
        """An unrecognized numbered book like '1 Foo' should report '1 Foo', not 'Foo'."""
        text = "See 1 Foo 3:4 for details."
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            result = find_unrecognized_abbreviations(text, ref_style)
        assert "1 Foo" in result
        assert "Foo" not in result

    def test_recognized_numbered_book_no_warning(self, ref_style, caplog):
        """A recognized numbered book like '1 Sm' should not warn."""
        text = "See 1 Sm 1:1 for details."
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            result = find_unrecognized_abbreviations(text, ref_style)
        assert result == {}

    def test_non_default_separator(self, caplog):
        """With a '.' separator, 'PL 39.243' should be detected."""
        dot_style = RefStyle(
            names=standard_names("en-cmos_short"), chapter_verse_separator="."
        )
        text = "See PL 39.243 for details."
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            result = find_unrecognized_abbreviations(text, dot_style)
        assert "PL" in result

    def test_digit_only_abbreviation_not_reported(self, ref_style, caplog):
        """A pattern like '1 39:243' where the book part is purely digits should not be reported."""
        text = "Column 1 39:243 is not a Bible reference."
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            result = find_unrecognized_abbreviations(text, ref_style)
        assert result == {}

    def test_whitelist_entry_suppresses_numbered_variant(self, ref_style, caplog):
        """Whitelisting 'PL' should also suppress '1 PL', '3 PL', etc."""
        text = "1 PL 39:243\n\n3 PL 12:5 for details."
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            result = find_unrecognized_abbreviations(text, ref_style, whitelist=["PL"])
        assert result == {}


class TestCrossVersificationMapping:
    """Foreign-versification references must be mapped before keying.

    A reference tagged with a foreign versification identifier must be
    mapped to the database's versification before its range keys are derived.
    """

    @staticmethod
    def _vulg_style():
        style = RefStyle.named("en-cmos_short")
        style.also_recognize_versifications({"Vulg.": "vulgata"})
        return style

    def test_foreign_reference_stored_under_mapped_key(self, tmp_path):
        """A Vulgate reference is stored under its mapped eng key.

        'Ps 50:1 Vulg.' in an eng database must be stored under the eng key
        for Ps 51:1 (19051001), not the raw vulgata key (18050001).
        """
        md = tmp_path / "test.md"
        md.write_text("Compare Ps 50:1 Vulg. with the psalm.", encoding="utf-8")
        db_path = tmp_path / "out.db"
        index_document(
            input_path=md,
            output_path=db_path,
            metadata={"title": "Test", "versification": "eng"},
            ref_style=self._vulg_style(),
        )
        with Database(db_path) as db:
            rows = db.conn.execute(
                "SELECT verse_start, verse_end FROM reference_index"
            ).fetchall()
        keys = [(r["verse_start"], r["verse_end"]) for r in rows]
        assert keys == [(19051001, 19051001)]

    def test_native_reference_still_stored_natively(self, tmp_path):
        """A reference without a foreign identifier keeps the db versification's keys."""
        md = tmp_path / "test.md"
        md.write_text("See Jn 3:16 here.", encoding="utf-8")
        db_path = tmp_path / "out.db"
        index_document(
            input_path=md,
            output_path=db_path,
            metadata={"title": "Test", "versification": "eng"},
            ref_style=self._vulg_style(),
        )
        with Database(db_path) as db:
            rows = db.conn.execute(
                "SELECT verse_start, verse_end FROM reference_index"
            ).fetchall()
        keys = [(r["verse_start"], r["verse_end"]) for r in rows]
        assert keys == [(43003016, 43003016)]


class TestIndexDocumentAbbreviationCheck:
    def test_check_abbreviations_false_suppresses(self, tmp_path, ref_style, caplog):
        md = tmp_path / "test.md"
        md.write_text("See PL 39:243 for details.", encoding="utf-8")
        db_path = tmp_path / "out.db"
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            index_document(
                input_path=md,
                output_path=db_path,
                metadata={"title": "Test", "versification": "eng"},
                ref_style=ref_style,
                check_abbreviations=False,
            )
        assert "PL" not in caplog.text

    def test_check_abbreviations_default_warns(self, tmp_path, ref_style, caplog):
        md = tmp_path / "test.md"
        md.write_text("See PL 39:243 for details.", encoding="utf-8")
        db_path = tmp_path / "out.db"
        with caplog.at_level(logging.WARNING, logger="versiref.search.indexer"):
            index_document(
                input_path=md,
                output_path=db_path,
                metadata={"title": "Test", "versification": "eng"},
                ref_style=ref_style,
            )
        assert 'Unrecognized abbreviation "PL"' in caplog.text


# --- Milestones and commentary scopes ---

PAGED_MD = """\
# Chapter One

First paragraph citing Lk 1:28. <!-- page: 12 --> Text on page twelve.

<!-- page: 13 -->

Paragraph on page thirteen citing Ps 45:10.
"""

COMMENTARY_MD = """\
# Commentary

Introduction without references.

## The Pericope Adulterae (Jn 7:53-8:11)

Introductory comments on the pericope.

### On Jn 8:7

Comment about the sinless one casting the first stone.

### On Jn 8:11

Comment about neither do I condemn you.

## The Light of the World (Jn 8:12)

Comment on the light of the world.
"""


@pytest.fixture
def paged_db(tmp_path, ref_style):
    md = tmp_path / "paged.md"
    md.write_text(PAGED_MD, encoding="utf-8")
    db_path = tmp_path / "paged.db"
    index_document(
        input_path=md,
        output_path=db_path,
        metadata={"title": "Paged", "versification": "eng"},
        ref_style=ref_style,
    )
    return db_path


@pytest.fixture
def commentary_db(tmp_path, ref_style):
    md = tmp_path / "commentary.md"
    md.write_text(COMMENTARY_MD, encoding="utf-8")
    db_path = tmp_path / "commentary.db"
    index_document(
        input_path=md,
        output_path=db_path,
        metadata={"title": "Commentary", "versification": "eng"},
        ref_style=ref_style,
        commentary_headings=True,
    )
    return db_path


def test_page_milestones_indexed(paged_db):
    stats = get_index_stats(paged_db)
    assert stats["milestone_count"] == 2
    with Database(paged_db) as db:
        # Block 2 holds the inline page-12 break; block 3 starts page 13.
        assert db.get_page_for_block(1) is None
        assert db.get_page_for_block(3) == "13"
        assert db.get_page_range("12") == (2, 3)


def test_page_markers_stripped_from_content(paged_db):
    with Database(paged_db) as db:
        _, text, _ = db.get_content_by_id(2)
        assert "<!--" not in text
        assert "page" not in text.lower() or "page twelve" in text


def test_heading_scopes_derived(commentary_db):
    stats = get_index_stats(commentary_db)
    assert stats["scope_count"] == 4
    with Database(commentary_db) as db:
        # Blocks: 1 h1, 2 intro, 3 h2 pericope, 4 para, 5 h3 (8:7), 6 para,
        # 7 h3 (8:11), 8 para, 9 h2 (8:12), 10 para.
        scopes = {
            (bs, be, vs, ve) for _, bs, be, vs, ve in db.search_scopes(0, 99999999)
        }
        assert (3, 8, 43007053, 43008011) in scopes  # pericope section
        assert (5, 6, 43008007, 43008007) in scopes  # per-verse section
        assert (7, 8, 43008011, 43008011) in scopes  # per-verse section
        assert (9, 10, 43008012, 43008012) in scopes  # sibling section to end


def test_heading_scopes_off_by_default(tmp_path, ref_style):
    md = tmp_path / "commentary.md"
    md.write_text(COMMENTARY_MD, encoding="utf-8")
    db_path = tmp_path / "plain.db"
    index_document(
        input_path=md,
        output_path=db_path,
        metadata={"title": "Commentary", "versification": "eng"},
        ref_style=ref_style,
    )
    assert get_index_stats(db_path)["scope_count"] == 0


EXPLICIT_SCOPE_MD = """\
# Appendix

<!-- scope: Jn 7:53-8:11 -->

Out-of-order commentary on the pericope, first paragraph.

Second paragraph.

<!-- scope: end -->

Unrelated closing paragraph.
"""


def test_explicit_scope_markers(tmp_path, ref_style):
    md = tmp_path / "appendix.md"
    md.write_text(EXPLICIT_SCOPE_MD, encoding="utf-8")
    db_path = tmp_path / "appendix.db"
    index_document(
        input_path=md,
        output_path=db_path,
        metadata={"title": "Appendix", "versification": "eng"},
        ref_style=ref_style,
    )
    with Database(db_path) as db:
        scopes = [
            (bs, be, vs, ve) for _, bs, be, vs, ve in db.search_scopes(0, 99999999)
        ]
        # Blocks: 1 h1, 2-3 commentary paragraphs, 4 closing paragraph.
        assert scopes == [(2, 3, 43007053, 43008011)]


def test_explicit_scope_open_at_document_end(tmp_path, ref_style):
    md = tmp_path / "openend.md"
    md.write_text(
        "First paragraph.\n\n<!-- scope: Jn 8:7 -->\n\nCommentary paragraph.\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "openend.db"
    index_document(
        input_path=md,
        output_path=db_path,
        metadata={"title": "Open", "versification": "eng"},
        ref_style=ref_style,
    )
    with Database(db_path) as db:
        scopes = [(bs, be) for _, bs, be, _, _ in db.search_scopes(0, 99999999)]
        assert scopes == [(2, 2)]


def test_invalid_scope_reference_warns_and_skips(tmp_path, ref_style, caplog):
    md = tmp_path / "bad.md"
    md.write_text(
        "<!-- scope: Not A Ref 99 -->\n\nA paragraph with Lk 1:28.\n", encoding="utf-8"
    )
    db_path = tmp_path / "bad.db"
    with caplog.at_level(logging.WARNING):
        index_document(
            input_path=md,
            output_path=db_path,
            metadata={"title": "Bad", "versification": "eng"},
            ref_style=ref_style,
        )
    assert any("could not be parsed" in r.message for r in caplog.records)
    assert get_index_stats(db_path)["scope_count"] == 0
