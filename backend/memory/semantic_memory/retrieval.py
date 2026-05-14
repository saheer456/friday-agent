"""
retrieval.py — Clean public API for FRIDAY semantic memory.

This is the only file that memory_manager.py interacts with directly.
"""
import asyncio
import logging
from pathlib import Path
from typing import List

from . import embedder, vector_store

logger = logging.getLogger("SemanticRetrieval")


async def initialize() -> None:
    """
    Warm up the embedding model and ChromaDB.
    Call this once at server startup — it is BLOCKING for the model load
    so that the first user request never races against model loading.
    """
    # Load synchronously on the main thread to avoid OneDrive WinError 6714
    embedder.load_model_sync()
    vector_store.init_chroma_sync()


async def semantic_search(query: str, limit: int = 3) -> List[str]:
    """
    Embed a query and return the top-k most semantically relevant memory texts.

    Returns a list of memory text strings, ranked by relevance.
    Returns an empty list if the system is not yet ready or has no memories.
    """
    if not embedder.is_ready() or not vector_store.is_ready():
        logger.debug("[Retrieval] Semantic search skipped — system not ready yet.")
        return []

    try:
        query_vector = await embedder.embed_text(query)
        results = await vector_store.search_memories(query_vector, limit=limit)

        # Filter out low-relevance matches (cosine similarity < 0.4)
        relevant = [r for r in results if r["score"] >= 0.4]

        if not relevant:
            return []

        return [r["text"] for r in relevant]

    except Exception as e:
        logger.error(f"[Retrieval] semantic_search failed: {e}")
        return []
