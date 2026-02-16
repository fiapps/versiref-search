"""Search texts for Bible references with versiref."""

from versiref.search.database import Database
from versiref.search.indexer import index_document, get_index_stats
from versiref.search.models import BlockInfo, Hit, SearchResult
from versiref.search.searcher import get_context, search_database

__all__ = [
    "BlockInfo",
    "Database",
    "Hit",
    "SearchResult",
    "get_context",
    "get_index_stats",
    "index_document",
    "search_database",
]
