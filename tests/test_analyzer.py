"""Tests for the analyzer module."""

from pathlib import Path

from versiref import RefStyle, Versification

from versiref.search import (
    VersificationScore,
    analyze_abbreviations,
    analyze_documents,
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _by_name(scores: list[VersificationScore]) -> dict[str, VersificationScore]:
    return {s.name: s for s in scores}


def test_returns_one_score_per_candidate(tmp_path, ref_style):
    md = _write(tmp_path, "doc.md", "He cites Lk 1:28 and Mt 5:3.\n")
    scores = analyze_documents([md], ref_style)
    expected = set(Versification.available_names())
    assert {s.name for s in scores} == expected
    assert len(scores) == len(expected)


def test_total_is_consistent_across_candidates(tmp_path, ref_style):
    md = _write(
        tmp_path, "doc.md", "He cites Lk 1:28 and Mt 5:3 and Ps 23:1 and Jn 3:16.\n"
    )
    scores = analyze_documents([md], ref_style)
    totals = {s.total for s in scores}
    assert len(totals) == 1, f"Expected one shared total, got {totals}"
    assert totals.pop() == 4


def test_english_refs_score_100_percent_for_eng(tmp_path, ref_style):
    md = _write(
        tmp_path, "doc.md", "He cites Lk 1:28 and Mt 5:3 and Ps 23:1 and Jn 3:16.\n"
    )
    by = _by_name(analyze_documents([md], ref_style))
    assert by["eng"].score == 1.0
    assert by["eng"].valid == by["eng"].total == 4


def test_psalm_numbering_distinguishes_lxx_from_eng(tmp_path, ref_style):
    # Ps 9:25 exists in lxx/vulgata (Ps 9 has 39 verses there) but not in
    # eng (20) or cei (21) or org (21). Ps 151:1 exists only in lxx.
    # Mt 5:3 keeps the pool size > 0 even for versifications that reject both.
    md = _write(
        tmp_path,
        "doc.md",
        "Compare Ps 9:25 with Ps 151:1, alongside Mt 5:3.\n",
    )
    by = _by_name(analyze_documents([md], ref_style))
    # lxx accepts all three; eng accepts only Mt 5:3.
    assert by["lxx"].score > by["eng"].score
    assert by["lxx"].score > by["cei"].score
    assert by["lxx"].valid == 3
    assert by["eng"].valid == 1


def test_multi_file_pools_references(tmp_path, ref_style):
    a = _write(tmp_path, "a.md", "He cites Lk 1:28.\n")
    b = _write(tmp_path, "b.md", "He cites Mt 5:3 and Jn 3:16.\n")
    by = _by_name(analyze_documents([a, b], ref_style))
    assert by["eng"].total == 3
    assert by["eng"].valid == 3


def test_empty_input_returns_zero_totals(tmp_path, ref_style):
    md = _write(tmp_path, "empty.md", "Nothing here.\n")
    scores = analyze_documents([md], ref_style)
    assert all(s.total == 0 for s in scores)
    assert all(s.score == 0.0 for s in scores)


def test_ranking_orders_by_score_descending(tmp_path, ref_style):
    md = _write(
        tmp_path,
        "doc.md",
        "Compare Ps 9:25 with Ps 151:1, alongside Mt 5:3.\n",
    )
    scores = analyze_documents([md], ref_style)
    score_values = [s.score for s in scores]
    assert score_values == sorted(score_values, reverse=True)
    # The lxx score is uniquely highest for this fixture.
    assert scores[0].name == "lxx"


def test_versification_score_dataclass_score_property():
    s = VersificationScore(name="eng", valid=3, total=4)
    assert s.score == 0.75
    s_zero = VersificationScore(name="eng", valid=0, total=0)
    assert s_zero.score == 0.0


def test_dedupe_across_versifications(tmp_path, ref_style):
    # Lk 1:28 is recognized by every candidate, so it would be scanned 9
    # times. The pool should still hold one entry, so total == 1.
    md = _write(tmp_path, "doc.md", "He cites Lk 1:28.\n")
    scores = analyze_documents([md], ref_style)
    assert all(s.total == 1 for s in scores)


# --- analyze_abbreviations ---


def test_abbreviations_all_recognized(tmp_path, ref_style):
    md = _write(tmp_path, "doc.md", "He cites Lk 1:28 and Mt 5:3.\n")
    result = analyze_abbreviations([md], ref_style)
    assert result.unrecognized == {}
    assert result.needed_sets == []
    assert result.remaining == {}


def test_abbreviations_truly_unrecognized_lands_in_remaining(tmp_path, ref_style):
    md = _write(tmp_path, "doc.md", "He cites Foobar 1:1.\n")
    result = analyze_abbreviations([md], ref_style)
    assert "Foobar" in result.unrecognized
    assert "Foobar" in result.remaining
    assert result.needed_sets == []


def test_abbreviations_unique_set_is_recommended(tmp_path, ref_style):
    # "1 Sam" is in en-sbl_abbreviations but not in en-cmos_short.recognized_names.
    md = _write(tmp_path, "doc.md", "He cites 1 Sam 3:4.\n")
    result = analyze_abbreviations([md], ref_style)
    assert "1 Sam" in result.unrecognized
    assert result.needed_sets == ["en-sbl_abbreviations"]
    assert result.remaining == {}


def test_abbreviations_greedy_picks_higher_coverage_first(tmp_path, ref_style):
    # Both abbrevs ("1 Sam" and "1 Pet") live only in en-sbl_abbreviations
    # among en-* sets — so a single set covers both. Verify the greedy step
    # picks one set rather than two.
    md = _write(tmp_path, "doc.md", "He cites 1 Sam 3:4 and 1 Pet 5:8.\n")
    result = analyze_abbreviations([md], ref_style)
    assert {"1 Sam", "1 Pet"} <= set(result.unrecognized)
    assert result.needed_sets == ["en-sbl_abbreviations"]


def test_abbreviations_language_prefix_scopes_candidates(tmp_path, ref_style):
    # "1 Samuele" is an Italian name, present in it-cei_nomi but not in any
    # en-* set. Style identifier "en-cmos_short" yields glob "en-*", so the
    # Italian name should fall through to `remaining`.
    md = _write(tmp_path, "doc.md", "He cites 1 Samuele 3:4.\n")
    result = analyze_abbreviations([md], ref_style)
    assert "1 Samuele" in result.unrecognized
    assert "1 Samuele" in result.remaining
    assert result.needed_sets == []


def test_abbreviations_no_language_prefix_uses_all_sets(tmp_path):
    # A style built from a dict has identifier=None, so the prefix regex
    # doesn't match and the analyzer falls back to glob "*". An it-*
    # abbrev *can* then be covered.
    style = RefStyle.from_dict({"base": "en-cmos_short"})
    assert style.identifier is None
    md = _write(tmp_path, "doc.md", "Cita 1 Samuele 3:4.\n")
    result = analyze_abbreviations([md], style)
    assert "1 Samuele" in result.unrecognized
    assert result.needed_sets == ["it-cei_nomi"]


def test_abbreviations_pool_across_files(tmp_path, ref_style):
    a = _write(tmp_path, "a.md", "He cites 1 Sam 3:4.\n")
    b = _write(tmp_path, "b.md", "He cites 1 Machabees 1:10.\n")
    result = analyze_abbreviations([a, b], ref_style)
    assert {"1 Sam", "1 Machabees"} <= set(result.unrecognized)
    assert set(result.needed_sets) == {
        "en-sbl_abbreviations",
        "en-douay-rheims_names",
    }
    assert result.remaining == {}
