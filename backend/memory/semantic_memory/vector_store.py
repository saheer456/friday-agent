"""
vector_store.py — Semantic memory vector persistence.

Storage strategy (auto-detected at runtime):
  - SUPABASE_URL + SUPABASE_KEY set  →  Supabase pgvector  (production)
  - Otherwise                         →  local ChromaDB      (dev)
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger("VectorStore")

# ChromaDB path (local dev fallback)
CHROMA_PATH     = Path(__file__).resolve().parent.parent.parent.parent / "data" / "chroma_db"
COLLECTION_NAME = "friday_semantic_memory"

# ChromaDB singletons
_client     = None
_collection = None
_lock       = asyncio.Lock()


def _use_supabase() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))


# ── Supabase pgvector backend ─────────────────────────────────────────────────

async def _sb_add_memory(memory_id: int, text: str, category: str,
                          importance: float, vector: List[float]) -> None:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        return
    try:
        await (
            sb.table("memory_embeddings")
            .upsert({
                "id":        memory_id,
                "embedding": vector,
                "text":      text[:2000],
                "category":  category,
                "importance": importance,
            })
            .execute()
        )
    except Exception as e:
        logger.error(f"[VectorStore] Supabase upsert failed: {e}")


async def _sb_search(query_vector: List[float], limit: int) -> List[Dict]:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        return []
    try:
        res = await sb.rpc(
            "match_memories",
            {
                "query_embedding": query_vector,
                "match_threshold": 0.4,
                "match_count":     limit,
            },
        ).execute()
        return res.data or []
    except Exception as e:
        logger.error(f"[VectorStore] Supabase search failed: {e}")
        return []


# ── ChromaDB fallback backend ─────────────────────────────────────────────────

def init_chroma_sync() -> None:
    global _client, _collection
    try:
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        import chromadb
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"[VectorStore] ✓ ChromaDB ready at {CHROMA_PATH}")
        print(f"[FRIDAY] ✓ Semantic vector store ready ({COLLECTION_NAME})")
    except Exception as e:
        logger.error(f"[VectorStore] ChromaDB init failed: {e}")


def is_ready() -> bool:
    if _use_supabase():
        from backend.supabase_client import is_available
        return is_available()
    return _collection is not None


# ── Public API ────────────────────────────────────────────────────────────────

async def add_memory(memory_id: int, text: str, category: str, importance: float) -> None:
    from . import embedder
    if not embedder.is_ready():
        return
    try:
        vector = await embedder.embed_text(text)
        if _use_supabase():
            await _sb_add_memory(memory_id, text, category, importance, vector)
        else:
            if _collection is None:
                return

            def _insert():
                _collection.upsert(
                    ids=[str(memory_id)],
                    embeddings=[vector],
                    documents=[text[:2000]],
                    metadatas=[{"category": category, "importance": importance}],
                )

            async with _lock:
                await asyncio.to_thread(_insert)
    except Exception as e:
        logger.error(f"[VectorStore] add_memory failed: {e}")


async def search_memories(query_vector: List[float], limit: int = 3) -> List[Dict]:
    if _use_supabase():
        rows = await _sb_search(query_vector, limit)
        # Normalise Supabase RPC response to match ChromaDB shape
        return [
            {
                "id":         r.get("id"),
                "text":       r.get("text", ""),
                "category":   r.get("category", "unknown"),
                "importance": r.get("importance", 0.5),
                "score":      r.get("similarity", 0.0),
            }
            for r in rows
        ]

    # ChromaDB path
    if _collection is None:
        return []

    def _query():
        count = _collection.count()
        if count == 0:
            return {}
        return _collection.query(
            query_embeddings=[query_vector],
            n_results=min(limit, count),
            include=["documents", "metadatas", "distances"],
        )

    try:
        async with _lock:
            results = await asyncio.to_thread(_query)
        if not results:
            return []

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
                "score":      1.0 - distances[i],
            }
            for i in range(len(docs))
        ]
    except Exception as e:
        logger.error(f"[VectorStore] ChromaDB search failed: {e}")
        return []
