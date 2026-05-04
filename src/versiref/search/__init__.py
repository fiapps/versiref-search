"""Search texts for Bible references with versiref."""

from versiref.search.analyzer import analyze_documents
from versiref.search.database import Database
from versiref.search.indexer import (
    InvalidRefAction,
    find_unrecognized_abbreviations,
    index_document,
    get_index_stats,
)
from versiref.search.models import BlockInfo, SearchResult, VersificationScore
from versiref.search.searcher import get_context, get_toc, search_database

__all__ = [
    "BlockInfo",
    "Database",
    "InvalidRefAction",
    "SearchResult",
    "VersificationScore",
    "analyze_documents",
    "find_unrecognized_abbreviations",
    "get_context",
    "get_index_stats",
    "get_toc",
    "index_document",
    "search_database",
]
