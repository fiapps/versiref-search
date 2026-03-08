"""Tests for the CLI search command."""

from pathlib import Path

from click.testing import CliRunner
from versiref import RefStyle

from versiref.search import index_document
from versiref.search.cli import main


MINIMAL_MD_A = """\
# Document A

Opening paragraph referencing Lk 1:28.

## Section A

Second paragraph citing Ps 45:10.
"""

MINIMAL_MD_B = """\
# Document B

A paragraph referencing Jn 3:16.

Another paragraph about Rom 8:28.
"""


def _make_db(tmp_path: Path, name: str, content: str, title: str) -> Path:
    md_path = tmp_path / f"{name}.md"
    md_path.write_text(content, encoding="utf-8")
    db_path = tmp_path / f"{name}.db"
    index_document(
        input_path=md_path,
        output_path=db_path,
        metadata={
            "title": title,
            "versification": "eng",
            "lang": "en",
        },
        ref_style=RefStyle.named("en-cmos_short"),
    )
    return db_path


def test_search_single_database(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["search", str(db), "-r", "Lk 1:28"])
    assert result.exit_code == 0
    assert "Lk 1:28" in result.output
    assert "1 result" in result.output
    # Single database should not show a header
    assert "---" not in result.output


def test_search_multiple_databases(tmp_path):
    db_a = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    db_b = _make_db(tmp_path, "doc_b", MINIMAL_MD_B, "Document B")
    runner = CliRunner()
    result = runner.invoke(main, ["search", str(db_a), str(db_b), "-r", "Lk 1:28"])
    assert result.exit_code == 0
    # Results from db_a
    assert "Lk 1:28" in result.output
    # Database headers shown
    assert "--- doc_a ---" in result.output
    assert "--- doc_b ---" in result.output


def test_search_multiple_databases_both_have_results(tmp_path):
    db_a = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    db_b = _make_db(tmp_path, "doc_b", MINIMAL_MD_B, "Document B")
    runner = CliRunner()
    result = runner.invoke(main, ["search", str(db_a), str(db_b), "-s", "paragraph"])
    assert result.exit_code == 0
    assert "--- doc_a ---" in result.output
    assert "--- doc_b ---" in result.output
    # Both databases have paragraphs with "paragraph"
    assert "<mark>" in result.output


def test_search_multiple_databases_no_results(tmp_path):
    db_a = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    db_b = _make_db(tmp_path, "doc_b", MINIMAL_MD_B, "Document B")
    runner = CliRunner()
    result = runner.invoke(main, ["search", str(db_a), str(db_b), "-s", "xyznotfound"])
    assert result.exit_code == 0
    assert "No results found in any database." in result.output


def test_search_no_query(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["search", str(db)])
    assert result.exit_code != 0
