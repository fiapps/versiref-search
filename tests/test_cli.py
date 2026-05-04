"""Tests for the CLI commands."""

from pathlib import Path

from click.testing import CliRunner
from versiref import RefStyle, Versification

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


def test_search_plain_annotates_heading_block_ids(tmp_path):
    # MINIMAL_MD_A block 3 = "## Section A"; the Ps 45:10 paragraph lives under it.
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["search", str(db), "-r", "Ps 45:10"])
    assert result.exit_code == 0
    assert "# Document A {block=1}" in result.output
    assert "## Section A {block=3}" in result.output


def test_search_xml_wraps_headings_with_block_tags(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["search", str(db), "-r", "Ps 45:10", "--xml"])
    assert result.exit_code == 0
    # Heading blocks and the matched block share the <block n="..."> form.
    assert '<block n="1">' in result.output
    assert "# Document A" in result.output
    assert '<block n="3">' in result.output
    assert "## Section A" in result.output
    assert '<block n="4">' in result.output


def test_search_start_end_limits_range(tmp_path):
    # MINIMAL_MD_A blocks: 1=h1, 2=Lk 1:28 paragraph, 3=h2, 4=Ps 45:10 paragraph
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()

    # Restrict to block 4 — Lk 1:28 in block 2 is out of range.
    result = runner.invoke(main, ["search", str(db), "-r", "Lk 1:28", "--start", "4"])
    assert result.exit_code == 0
    assert "No results found" in result.output

    # Open range that includes block 2 finds Lk 1:28.
    result = runner.invoke(
        main, ["search", str(db), "-r", "Lk 1:28", "--start", "1", "--end", "3"]
    )
    assert result.exit_code == 0
    assert "Lk 1:28" in result.output


def test_search_start_greater_than_end_errors(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(
        main, ["search", str(db), "-s", "paragraph", "--start", "5", "--end", "2"]
    )
    assert result.exit_code != 0
    assert "--start" in result.output


# --- toc command ---


def test_toc_default_depth(tmp_path):
    # MINIMAL_MD_A: block 1 = "# Document A", block 3 = "## Section A"
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["toc", str(db)])
    assert result.exit_code == 0
    assert "# Document A {block=1}" in result.output
    assert "## Section A {block=3}" in result.output


def test_toc_depth_one_excludes_h2(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["toc", str(db), "--depth", "1"])
    assert result.exit_code == 0
    assert "# Document A {block=1}" in result.output
    assert "Section A" not in result.output


def test_toc_range_filter(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["toc", str(db), "--start", "2"])
    assert result.exit_code == 0
    assert "Document A" not in result.output
    assert "## Section A {block=3}" in result.output


def test_toc_xml(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["toc", str(db), "--xml"])
    assert result.exit_code == 0
    assert "<toc>" in result.output
    assert '<block n="1">' in result.output
    assert "# Document A" in result.output
    assert "</block>" in result.output
    assert "</toc>" in result.output


def test_toc_no_headings_in_range(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["toc", str(db), "--start", "100"])
    assert result.exit_code == 0
    assert "No headings found." in result.output


def test_toc_start_greater_than_end_errors(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["toc", str(db), "--start", "5", "--end", "2"])
    assert result.exit_code != 0
    assert "--start" in result.output


# --- info command ---


def test_info_single_database(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["info", str(db)])
    assert result.exit_code == 0
    assert "title: Document A" in result.output
    assert "versification_scheme: eng" in result.output
    assert "blocks:" in result.output
    assert "references:" in result.output
    # Single database should not show a header
    assert "---" not in result.output


def test_info_multiple_databases(tmp_path):
    db_a = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    db_b = _make_db(tmp_path, "doc_b", MINIMAL_MD_B, "Document B")
    runner = CliRunner()
    result = runner.invoke(main, ["info", str(db_a), str(db_b)])
    assert result.exit_code == 0
    assert "--- doc_a ---" in result.output
    assert "--- doc_b ---" in result.output
    assert "title: Document A" in result.output
    assert "title: Document B" in result.output


# --- analyze command ---


def test_analyze_lists_every_candidate(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites Lk 1:28 and Mt 5:3.\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(md)])
    assert result.exit_code == 0
    assert "Analyzed 1 file(s)" in result.output
    for name in Versification.available_names():
        assert name in result.output


def test_analyze_multiple_files_combined(tmp_path):
    a = tmp_path / "a.md"
    a.write_text("He cites Lk 1:28.\n", encoding="utf-8")
    b = tmp_path / "b.md"
    b.write_text("He cites Mt 5:3.\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(a), str(b)])
    assert result.exit_code == 0
    assert "Analyzed 2 file(s)" in result.output
    assert "2 reference(s) in pool" in result.output


def test_analyze_empty_input_exits_nonzero(tmp_path):
    md = tmp_path / "empty.md"
    md.write_text("Nothing here.\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(md)])
    assert result.exit_code != 0
    assert "No references found" in result.output


def test_analyze_psalm_fixture_ranks_lxx_first(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text(
        "Compare Ps 9:25 with Ps 151:1, alongside Mt 5:3.\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(md)])
    assert result.exit_code == 0
    # First data row after the header should be lxx.
    lines = result.output.splitlines()
    header_index = next(
        i for i, ln in enumerate(lines) if ln.startswith("Versification")
    )
    first_row = lines[header_index + 1]
    assert first_row.split()[0] == "lxx"
