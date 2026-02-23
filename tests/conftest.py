"""Shared fixtures for versiref-search tests."""

import pytest
from pathlib import Path
from versiref import RefStyle

from versiref.search import index_document

SAMPLE_MD = Path(__file__).parent.parent / "docs" / "sample" / "speculum-bvm-ch01.md"

MINIMAL_MD_CONTENT = """\
# Chapter One

Opening paragraph referencing Lk 1:28.

## Section A

Second paragraph citing Ps 45:10.

Third paragraph with no references.
"""


@pytest.fixture(scope="session")
def ref_style():
    """Standard reference style used across tests."""
    return RefStyle.named("en-cmos_short")


@pytest.fixture
def minimal_md(tmp_path):
    """A small Markdown file with two Bible references in separate paragraphs."""
    path = tmp_path / "test.md"
    path.write_text(MINIMAL_MD_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def indexed_db(tmp_path, minimal_md, ref_style):
    """SQLite database indexed from minimal_md."""
    db_path = tmp_path / "test.db"
    index_document(
        input_path=minimal_md,
        output_path=db_path,
        versification="eng",
        title="Test Document",
        ref_style=ref_style,
        lang="en",
        author="Test Author",
    )
    return db_path
