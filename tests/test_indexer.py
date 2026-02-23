"""Tests for the indexer module."""

import pytest
from pathlib import Path

from versiref.search import index_document, get_index_stats
from versiref.search.database import SCHEMA_VERSION

SAMPLE_MD = Path(__file__).parent.parent / "docs" / "sample" / "speculum-bvm-ch01.md"


def test_missing_input_raises(tmp_path, ref_style):
    with pytest.raises(FileNotFoundError):
        index_document(
            input_path=tmp_path / "nonexistent.md",
            output_path=tmp_path / "out.db",
            versification="eng",
            title="Test",
            ref_style=ref_style,
        )


def test_invalid_versification_raises(tmp_path, minimal_md, ref_style):
    with pytest.raises(ValueError, match="versification"):
        index_document(
            input_path=minimal_md,
            output_path=tmp_path / "out.db",
            versification="not_a_real_scheme",
            title="Test",
            ref_style=ref_style,
        )


def test_creates_database_file(tmp_path, minimal_md, ref_style):
    db_path = tmp_path / "out.db"
    assert not db_path.exists()
    index_document(
        input_path=minimal_md,
        output_path=db_path,
        versification="eng",
        title="Test",
        ref_style=ref_style,
    )
    assert db_path.exists()


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


def test_author_omitted_when_not_provided(tmp_path, minimal_md, ref_style):
    db_path = tmp_path / "out.db"
    index_document(
        input_path=minimal_md,
        output_path=db_path,
        versification="eng",
        title="No Author",
        ref_style=ref_style,
    )
    meta = get_index_stats(db_path)["metadata"]
    assert "author" not in meta


def test_get_index_stats_missing_db(tmp_path):
    with pytest.raises(FileNotFoundError):
        get_index_stats(tmp_path / "nonexistent.db")


def test_sample_file_block_and_reference_counts(tmp_path, ref_style):
    """Integration test: index the actual sample file and verify known counts."""
    db_path = tmp_path / "speculum.db"
    index_document(
        input_path=SAMPLE_MD,
        output_path=db_path,
        versification="eng",
        title="Speculum BVM",
        ref_style=ref_style,
    )
    stats = get_index_stats(db_path)
    assert stats["block_count"] == 17
    assert stats["reference_count"] == 4
