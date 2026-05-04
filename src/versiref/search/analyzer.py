"""Analyze Markdown documents to detect their versification scheme."""

from collections.abc import Sequence
from pathlib import Path

from versiref import BibleRef, RefParser, RefStyle, Sensitivity, Versification

from .markdown_parser import parse_markdown
from .models import VersificationScore


def analyze_documents(
    input_paths: Sequence[str | Path],
    ref_style: RefStyle,
    *,
    parser_sensitivity: Sensitivity = Sensitivity.VERSE,
    candidates: Sequence[str] | None = None,
) -> list[VersificationScore]:
    """Score each candidate versification by validity of references in the input.

    Each input file is parsed into Markdown blocks. For every candidate
    versification, the blocks are scanned for Bible references; the union of
    hits (deduped by character span) becomes the reference pool. Each candidate
    is then scored by the fraction of pool entries that are valid in it.

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

    pool: dict[tuple[Path, int, int, int], BibleRef] = {}
    for raw_path in input_paths:
        path = Path(raw_path)
        markdown_text = path.read_text(encoding="utf-8")
        blocks = parse_markdown(markdown_text)
        for name, vers in versifications.items():
            parser = RefParser(ref_style, vers)
            for block in blocks:
                for ref, start_pos, end_pos in parser.scan_string(
                    block.text, sensitivity=parser_sensitivity
                ):
                    key = (path, block.id, start_pos, end_pos)
                    pool.setdefault(key, ref)

    scores: list[VersificationScore] = []
    for index, name in enumerate(candidates):
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
