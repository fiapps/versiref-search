"""Search texts for Bible references with versiref."""

from versiref.search.database import Database
from versiref.search.indexer import (
    InvalidRefAction,
    find_unrecognized_abbreviations,
    index_document,
    get_index_stats,
)
from versiref.search.models import BlockInfo, SearchResult
from versiref.search.searcher import get_context, search_database

__all__ = [
    "BlockInfo",
    "Database",
    "InvalidRefAction",
    "SearchResult",
    "find_unrecognized_abbreviations",
    "get_context",
    "get_index_stats",
    "index_document",
    "search_database",
]
