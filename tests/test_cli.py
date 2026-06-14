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


# --- show command ---
# MINIMAL_MD_A: 1 "# Document A", 2 para (Lk 1:28), 3 "## Section A",
# 4 para (Ps 45:10).


def test_show_explicit_range(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["show", str(db), "--start", "2", "--end", "2"])
    assert result.exit_code == 0
    assert "[Block 2]" in result.output
    assert "Lk 1:28" in result.output


def test_show_range_requires_start_and_end(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["show", str(db), "--start", "2"])
    assert result.exit_code != 0
    assert "--start and --end are required" in result.output


def test_show_section_by_block(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["show", str(db), "--start", "4", "--section", "2"])
    assert result.exit_code == 0
    assert "## Section A" in result.output
    assert "Ps 45:10" in result.output
    # The h1 above the section is not included without --include-headings.
    assert "Document A" not in result.output


def test_show_section_include_headings(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(
        main, ["show", str(db), "--start", "4", "--section", "2", "--include-headings"]
    )
    assert result.exit_code == 0
    assert "# Document A" in result.output
    assert "## Section A" in result.output


def test_show_section_by_heading(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(
        main, ["show", str(db), "--heading", "Section A", "--section", "2"]
    )
    assert result.exit_code == 0
    assert "## Section A" in result.output
    assert "Ps 45:10" in result.output


def test_show_section_too_large(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(
        main, ["show", str(db), "--start", "2", "--section", "1", "--max-blocks", "1"]
    )
    assert result.exit_code != 0
    assert "max 1" in result.output
    assert "--max-blocks" in result.output


def test_show_heading_requires_section(tmp_path):
    db = _make_db(tmp_path, "doc_a", MINIMAL_MD_A, "Document A")
    runner = CliRunner()
    result = runner.invoke(main, ["show", str(db), "--heading", "Section A"])
    assert result.exit_code != 0
    assert "--heading requires --section" in result.output


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
    assert "Reference pool: 2 reference(s)" in result.output


def test_analyze_empty_input_exits_nonzero(tmp_path):
    md = tmp_path / "empty.md"
    md.write_text("Nothing here.\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(md)])
    assert result.exit_code != 0
    assert "Reference pool: 0 reference(s)" in result.output


def test_analyze_reports_all_abbreviations_recognized(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites Lk 1:28 and Mt 5:3.\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(md)])
    assert result.exit_code == 0
    assert "All abbreviations are recognized" in result.output


def test_analyze_recommends_set_for_unrecognized_abbreviation(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites 1 Sam 3:4.\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(md)])
    assert result.exit_code == 0
    assert "Additional book-name sets needed (en-*)" in result.output
    assert "en-sbl_abbreviations" in result.output


def test_analyze_lists_uncovered_abbreviation(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites Foobar 1:1.\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(md)])
    assert "Names not covered by any set:" in result.output
    assert "Foobar" in result.output


def test_analyze_pool_includes_refs_after_set_enrichment(tmp_path):
    # "1 Sam 3:4" is unrecognized by en-cmos_short alone, so without the
    # also_recognize step the parser would skip it and the reference pool
    # would be empty. After enrichment with en-sbl_abbreviations, the ref
    # is parsed and ends up in the pool.
    md = tmp_path / "doc.md"
    md.write_text("He cites 1 Sam 3:4.\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", str(md)])
    assert result.exit_code == 0
    assert "Reference pool: 1 reference(s)" in result.output


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
    header_index = next(i for i, ln in enumerate(lines) if "Versification" in ln)
    first_row = lines[header_index + 1]
    # Strip the leading marker column (single char + space) before parsing
    # the row, since unmarked rows lead with two spaces.
    assert first_row[2:].split()[0] == "lxx"


def test_analyze_config_whitelist_suppresses_abbreviation(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites Foobar 1:1 and Lk 1:28.\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "abbreviations_whitelist:\n  - Foobar\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "-c", str(config), str(md)])
    assert result.exit_code == 0
    assert "Foobar" not in result.output
    assert "All abbreviations are recognized" in result.output


def test_analyze_config_marks_configured_versification(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites Lk 1:28 and Mt 5:3.\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("versification: lxx\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "-c", str(config), str(md)])
    assert result.exit_code == 0
    # The lxx row carries the leading asterisk.
    lxx_rows = [ln for ln in result.output.splitlines() if " lxx " in ln + " "]
    assert any(ln.startswith("* lxx") for ln in lxx_rows)
    assert "configured versification (lxx)" in result.output


def test_analyze_config_versification_match_is_case_insensitive(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites Lk 1:28 and Mt 5:3.\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("versification: Vulgata\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "-c", str(config), str(md)])
    assert result.exit_code == 0
    # Marker lands on the canonical "vulgata" row, and the legend uses the
    # canonical name too.
    assert any(ln.startswith("* vulgata") for ln in result.output.splitlines())
    assert "configured versification (vulgata)" in result.output


def test_analyze_config_pulls_versification_from_metadata(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites Lk 1:28.\n", encoding="utf-8")
    metadata = tmp_path / "metadata.yaml"
    metadata.write_text("title: Sample\nversification: eng\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("metadata: metadata.yaml\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "-c", str(config), str(md)])
    assert result.exit_code == 0
    assert "configured versification (eng)" in result.output


def test_analyze_config_unknown_versification_warns(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites Lk 1:28.\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("versification: nonesuch\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "-c", str(config), str(md)])
    assert result.exit_code == 0
    assert "'nonesuch' is not a known scheme" in result.output


def test_analyze_config_inline_style_recognizes_custom_abbreviation(tmp_path):
    # "ZZ" is not a normal Bible abbreviation; an inline style mapping it to
    # MAT (Matthew) lets the parser pick up "ZZ 1:1" without warning.
    md = tmp_path / "doc.md"
    md.write_text("He cites ZZ 1:1.\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "style:\n  base: en-cmos_short\n  also_recognize:\n    - ZZ: MAT\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["analyze", "-c", str(config), str(md)])
    assert result.exit_code == 0
    assert "All abbreviations are recognized" in result.output


def test_analyze_cli_style_overrides_config(tmp_path):
    md = tmp_path / "doc.md"
    md.write_text("He cites 1 Sam 3:4.\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    # Config sets a style that would also fail to recognize "1 Sam", but
    # the CLI flag should take precedence anyway. We're really just
    # verifying that no error arises from the override interaction.
    config.write_text("style: en-cmos_short\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(
        main, ["analyze", "-c", str(config), "--style", "en-sbl", str(md)]
    )
    assert result.exit_code == 0
    # en-sbl already recognizes "1 Sam", so nothing should be flagged.
    assert "All abbreviations are recognized" in result.output
