"""Search texts for Bible references with versiref."""

from versiref.search.analyzer import analyze_abbreviations, analyze_documents
from versiref.search.database import Database, IncompatibleDatabaseError
from versiref.search.indexer import (
    InvalidRefAction,
    find_unrecognized_abbreviations,
    index_document,
    get_index_stats,
)
from versiref.search.models import (
    AbbreviationAnalysis,
    BlockInfo,
    RawMilestone,
    ScopeResult,
    SearchResult,
    VersificationScore,
)
from versiref.search.searcher import (
    AmbiguousSectionError,
    SectionTooLargeError,
    get_context,
    get_page_context,
    get_section_by_block,
    get_section_by_heading,
    get_toc,
    search_commentary,
    search_database,
)

__all__ = [
    "AbbreviationAnalysis",
    "AmbiguousSectionError",
    "BlockInfo",
    "Database",
    "IncompatibleDatabaseError",
    "InvalidRefAction",
    "RawMilestone",
    "ScopeResult",
    "SearchResult",
    "SectionTooLargeError",
    "VersificationScore",
    "analyze_abbreviations",
    "analyze_documents",
    "find_unrecognized_abbreviations",
    "get_context",
    "get_index_stats",
    "get_page_context",
    "get_section_by_block",
    "get_section_by_heading",
    "get_toc",
    "index_document",
    "search_commentary",
    "search_database",
]
