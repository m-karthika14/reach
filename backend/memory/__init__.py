"""Phase 9 - persistent memory + RAG (Firestore db 'reach-memory').

    page_memory  correction_memory  preference_memory  task_history

Memory is a HINT, never authority: the current page always wins, and page
knowledge is only strengthened after a Phase 8 VERIFIED result.
"""

from .preferences import PreferenceProfile, preference_store
from .retrieval import MemoryRetriever, match_corrections_to_candidates, render_memory
from .util import domain_of, page_of
from .writer import MemoryWriter

_retriever: MemoryRetriever | None = None
_writer: MemoryWriter | None = None


def retriever() -> MemoryRetriever:
    global _retriever
    if _retriever is None:
        _retriever = MemoryRetriever()
    return _retriever


def writer() -> MemoryWriter:
    global _writer
    if _writer is None:
        _writer = MemoryWriter()
    return _writer


__all__ = [
    "MemoryRetriever", "MemoryWriter", "render_memory", "match_corrections_to_candidates",
    "PreferenceProfile", "preference_store",
    "retriever", "writer", "domain_of", "page_of",
]
