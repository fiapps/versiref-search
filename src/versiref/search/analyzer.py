"""Analyze Markdown documents to detect their versification scheme."""

import re
from collections.abc import Sequence
from pathlib import Path

from versiref import (
    BibleRef,
    RefParser,
    RefStyle,
    Sensitivity,
    Versification,
    available_standard_names,
    standard_names,
)

from .models import AbbreviationAnalysis, VersificationScore


_LANG_PREFIX_RE = re.compile(r"^([a-z]{2,3})-")


def _scan_unrecognized(text: str, ref_style: RefStyle) -> dict[str, str]:
    """Find candidate book abbreviations in `text` not in `ref_style.recognized_names`.

    Returns a mapping of abbreviation to an example of usage.
    """
    sep = re.escape(ref_style.chapter_verse_separator)
    pattern = rf"((?:[1-4]|[IV]+)\s+)?(\w[\w()]*)\s+\d+{sep}\d+"
    recognized = ref_style.recognized_names
    unrecognized: dict[str, str] = {}
    for match in re.finditer(pattern, text):
        leading = match.group(1)
        book_name = match.group(2)
        if book_name.isdigit():
            continue
        abbrev = leading + book_name if leading else book_name
        if abbrev in recognized:
            continue
        if leading and book_name in recognized:
            continue
        unrecognized.setdefault(abbrev, match.group(0))
    return unrecognized


def analyze_abbreviations(
    input_paths: Sequence[str | Path],
    ref_style: RefStyle,
    *,
    abbreviation_whitelist: Sequence[str] | None = None,
) -> AbbreviationAnalysis:
    """Find unrecognized book abbreviations and recommend covering name sets.

    Scans each input file for things that look like Scripture references
    (using a regex built from ``ref_style.chapter_verse_separator``) and
    keeps the abbreviations the style does not recognize. Then, from the
    bundled :func:`versiref.standard_names` collections matching the
    style's language prefix (e.g. ``en-*``), greedily picks the smallest
    list of sets that cover those abbreviations.

    Args:
        input_paths: One or more Markdown (or plain text) files.
        ref_style: RefStyle controlling the chapter/verse separator and
            the baseline recognized abbreviations.
        abbreviation_whitelist: Abbreviations to treat as recognized — they
            are dropped from the unrecognized set before greedy coverage,
            so they appear in neither the report nor the recommended sets.

    Returns:
        An AbbreviationAnalysis with the unrecognized abbreviations, the
        ordered list of recommended name sets, and any leftover names not
        covered by any bundled set.

    """
    whitelist = set(abbreviation_whitelist or ())
    unrecognized: dict[str, str] = {}
    for raw_path in input_paths:
        text = Path(raw_path).read_text(encoding="utf-8")
        for abbrev, example in _scan_unrecognized(text, ref_style).items():
            if abbrev in whitelist:
                continue
            unrecognized.setdefault(abbrev, example)

    identifier = ref_style.identifier or ""
    match = _LANG_PREFIX_RE.match(identifier)
    glob = f"{match.group(1)}-*" if match else "*"
    candidates = {
        name: {v for v in standard_names(name).values() if v}
        for name in available_standard_names(glob)
    }

    needed_sets: list[str] = []
    remaining = set(unrecognized)
    while remaining:
        best_name: str | None = None
        best_count = 0
        for name, coverage in candidates.items():
            count = len(coverage & remaining)
            if count > best_count:
                best_count = count
                best_name = name
        if best_name is None:
            break
        needed_sets.append(best_name)
        remaining -= candidates.pop(best_name)

    return AbbreviationAnalysis(
        unrecognized=unrecognized,
        needed_sets=needed_sets,
        remaining={a: unrecognized[a] for a in sorted(remaining)},
    )


def analyze_documents(
    input_paths: Sequence[str | Path],
    ref_style: RefStyle,
    *,
    parser_sensitivity: Sensitivity = Sensitivity.VERSE,
    candidates: Sequence[str] | None = None,
) -> list[VersificationScore]:
    """Score each candidate versification by validity of references in the input.

    For every candidate versification, each input file is scanned for Bible
    references; the union of hits (deduped by file and character span)
    becomes the reference pool. Each candidate is then scored by the
    fraction of pool entries that are valid in it.

    Args:
        input_paths: One or more Markdown files to analyze.
        ref_style: RefStyle controlling how book names are recognized.
        parser_sensitivity: Sensitivity level for reference scanning.
        candidates: Versification identifiers to evaluate. Defaults to every
            scheme returned by ``Versification.available_names()``.

    Returns:
        A list of VersificationScore objects sorted by score (descending),
        with ties broken by absolute valid count, then by candidate order.

    """
    if candidates is None:
        candidates = Versification.available_names()
    versifications = {name: Versification.named(name) for name in candidates}

    # Each versification gets its own parser, so a reference at the same
    # span gets visited once per scheme. The dedupe key folds those
    # repeated hits into one pool entry.
    pool: dict[tuple[Path, int, int], BibleRef] = {}
    for raw_path in input_paths:
        path = Path(raw_path)
        text = path.read_text(encoding="utf-8")
        for vers in versifications.values():
            parser = RefParser(ref_style, vers)
            for ref, start_pos, end_pos in parser.scan_string(
                text, sensitivity=parser_sensitivity
            ):
                pool.setdefault((path, start_pos, end_pos), ref)

    scores: list[VersificationScore] = []
    for name in candidates:
        vers = versifications[name]
        valid = 0
        total = 0
        for ref in pool.values():
            for sr in ref.simple_refs:
                total += 1
                if sr.is_valid(vers):
                    valid += 1
        scores.append(VersificationScore(name=name, valid=valid, total=total))

    candidate_order = {name: i for i, name in enumerate(candidates)}
    scores.sort(key=lambda s: (-s.score, -s.valid, candidate_order[s.name]))
    return scores
