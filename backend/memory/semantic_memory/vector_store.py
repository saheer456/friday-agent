"""
vector_store.py — ChromaDB persistence layer for FRIDAY semantic memory.

All public functions are async-safe. ChromaDB itself is synchronous,
so every write/read is dispatched via asyncio.to_thread() with a shared lock.
"""
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("VectorStore")

# ── Constants ─────────────────────────────────────────────────────────────────
CHROMA_PATH       = Path(__file__).resolve().parent.parent.parent.parent / "data" / "chroma_db"
COLLECTION_NAME   = "friday_semantic_memory"

# ── Singletons ────────────────────────────────────────────────────────────────
_client     = None
_collection = None
_lock       = asyncio.Lock()  # Serialises all ChromaDB operations


def init_chroma_sync() -> None:
    """Blocking init — call once at startup via run_in_executor."""
    global _client, _collection
    try:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        import chromadb
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}  # Cosine similarity — best for text
        )
        logger.info(f"[VectorStore] ✓ ChromaDB initialized at {CHROMA_PATH}")
        print(f"[FRIDAY] ✓ Semantic vector store ready ({COLLECTION_NAME})")
    except Exception as e:
        logger.error(f"[VectorStore] Init failed: {e}")


def is_ready() -> bool:
    return _collection is not None


async def add_memory(memory_id: int, text: str, category: str, importance: float) -> None:
    """Embed and insert a memory into the vector store."""
    if not is_ready():
        return
    from . import embedder
    if not embedder.is_ready():
        return

    try:
        vector = await embedder.embed_text(text)

        def _insert():
            _collection.upsert(
                ids=[str(memory_id)],
                embeddings=[vector],
                documents=[text[:2000]],
                metadatas=[{"category": category, "importance": importance}]
            )

        async with _lock:
            await asyncio.to_thread(_insert)

        logger.debug(f"[VectorStore] Added memory id={memory_id} category={category}")
    except Exception as e:
        logger.error(f"[VectorStore] add_memory failed: {e}")


async def search_memories(query_vector: List[float], limit: int = 3) -> List[Dict]:
    """
    Return the top-k most semantically similar memories.
    Returns list of dicts with keys: id, text, category, importance, distance.
    """
    if not is_ready():
        return []

    def _query():
        return _collection.query(
            query_embeddings=[query_vector],
            n_results=min(limit, _collection.count()),
            include=["documents", "metadatas", "distances"]
        )

    try:
        async with _lock:
            results = await asyncio.to_thread(_query)

        docs      = results.get("documents", [[]])[0]
        metas     = results.get("metadatas",  [[]])[0]
        distances = results.get("distances",  [[]])[0]
        ids       = results.get("ids",        [[]])[0]

        return [
            {
                "id":         ids[i],
                "text":       docs[i],
                "category":   metas[i].get("category", "unknown"),
                "importance": metas[i].get("importance", 0.5),
                "score":      1.0 - distances[i],  # cosine → similarity
            }
            for i in range(len(docs))
        ]
    except Exception as e:
        logger.error(f"[VectorStore] search failed: {e}")
        return []
