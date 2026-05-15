"""
retrieval.py — Safe lazy-loading semantic memory layer
"""

import logging
from typing import List

logger = logging.getLogger("SemanticRetrieval")

_embedder = None
_vector_store = None


def _lazy_imports():
    global _embedder, _vector_store

    if _embedder is None or _vector_store is None:
        logger.info("[Retrieval] Lazy-loading semantic memory modules...")

        from . import embedder
        from . import vector_store

        _embedder = embedder
        _vector_store = vector_store

        logger.info("[Retrieval] ✓ Semantic memory modules loaded")


async def initialize() -> None:
    """
    Warm up embedding model + ChromaDB safely.
    """

    try:
        _lazy_imports()

        logger.info("[Retrieval] Loading embedding model...")

        _embedder.load_model_sync()

        logger.info("[Retrieval] Initializing ChromaDB...")

        _vector_store.init_chroma_sync()

        logger.info("[Retrieval] ✓ Semantic memory ready")

    except Exception as e:
        logger.exception(f"[Retrieval] Initialization failed: {e}")


async def semantic_search(query: str, limit: int = 3) -> List[str]:
    """
    Semantic search over memory embeddings.
    """

    try:
        _lazy_imports()

        if not _embedder.is_ready():
            logger.warning("[Retrieval] Embedder not ready")
            return []

        if not _vector_store.is_ready():
            logger.warning("[Retrieval] Vector store not ready")
            return []

        query_vector = await _embedder.embed_text(query)

        results = await _vector_store.search_memories(
            query_vector,
            limit=limit
        )

        relevant = [
            r for r in results
            if r.get("score", 0) >= 0.4
        ]

        return [r["text"] for r in relevant]

    except Exception as e:
        logger.exception(f"[Retrieval] semantic_search failed: {e}")
        return []