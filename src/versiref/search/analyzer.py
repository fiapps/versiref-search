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

# Well-formed Roman numeral up to 499 (chapters never exceed CL), in either
# subtractive ("XLIV") or additive ("XXXXIIII") style. The character classes
# in _scan_unrecognized guarantee the candidate is nonempty and single-case.
_ROMAN_NUMERAL_RE = re.compile(
    r"C{0,4}(?:XC|XL|L?X{0,4})(?:IX|IV|V?I{0,4})", re.IGNORECASE
)


def _scan_unrecognized(text: str, ref_style: RefStyle) -> dict[str, str]:
    """Find candidate book abbreviations in `text` not in `ref_style.recognized_names`.

    Returns a mapping of abbreviation to an example of usage.
    """
    sep = re.escape(ref_style.chapter_verse_separator)
    roman = ref_style.chapter_number_style in ("roman", "roman-lower")
    if ref_style.chapter_number_style == "roman":
        chapter = r"[CLXVI]+(?![0-9A-Za-zÆæŒœ])"
    elif ref_style.chapter_number_style == "roman-lower":
        chapter = r"[clxvi]+(?![0-9A-Za-zÆæŒœ])"
    else:
        chapter = r"\d+"
    pattern = rf"((?:[1-4]|[IV]+)\s+)?(\w[\w()]*\.?)\s+({chapter}){sep}\d+"
    recognized = ref_style.recognized_names
    unrecognized: dict[str, str] = {}
    for match in re.finditer(pattern, text):
        leading = match.group(1)
        book_name = match.group(2)
        if book_name.rstrip(".").isdigit():
            continue
        if roman and not _ROMAN_NUMERAL_RE.fullmatch(match.group(3)):
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
    keeps the abbreviations the style does not recognize. When the style's
    ``chapter_number_style`` is ``"roman"`` or ``"roman-lower"``, chapter
    numbers are matched as Roman numerals (rejecting letter sequences that
    do not form a well-formed numeral); otherwise they are Arabic digits. Then, from the
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

    Each input file is scanned once for Bible references; the resulting
    set of unique references is then scored against every candidate
    versification by the fraction that are valid in it.

    Scanning is versification-independent: the only thing the parser uses
    a versification for is to tell whether a number after a book name is a
    chapter or a verse, and that hinges on the set of single-chapter books,
    which is the same across all known schemes.

    Repeated citations of the same reference count once: each parsed
    reference is canonicalized via ``ref_style`` before deduplication, so
    "Lk 1:28" and "Luke 1:28" fold together. The ranking therefore
    reflects the diversity of references covered rather than how often a
    popular verse is cited.

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

    # Any versification will do for scanning; pick the first candidate.
    # BibleRef isn't hashable, so dedupe by the canonical formatted form
    # — this folds "Lk 1:28" and "Luke 1:28" into the same pool entry.
    parser = RefParser(ref_style, next(iter(versifications.values())))
    pool: dict[str, BibleRef] = {}
    for raw_path in input_paths:
        text = Path(raw_path).read_text(encoding="utf-8")
        for ref, _, _ in parser.scan_string(text, sensitivity=parser_sensitivity):
            pool.setdefault(ref.format(ref_style), ref)

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
