import asyncio
import logging
from typing import List, Dict

from . import short_term
from . import long_term
from . import memory_ranker
from .semantic_memory import semantic_search, initialize as _sem_initialize

logger = logging.getLogger("MemoryManager")


class MemoryManager:
    """Orchestrates short-term buffer, ranking, SQLite and ChromaDB vector storage."""

    @classmethod
    async def initialize(cls) -> None:
        """
        Call on application startup.
        Initializes the SQLite DB and boots the embedding model + ChromaDB.
        """
        await long_term.init_db()
        short_term.clear_buffer()
        # Fire up the semantic layer (model load is blocking internally but wrapped async)
        await _sem_initialize()

    @classmethod
    async def save_memory(cls, user_msg: str, ai_response: str) -> None:
        """
        1. Add to short-term rolling buffer (instant).
        2. Evaluate importance via LLM ranker.
        3. If importance >= 0.4: persist to SQLite AND embed into ChromaDB.
        """
        # 1. Short-Term
        short_term.add_exchange(user_msg, ai_response)

        # 2. Evaluate
        exchange_text = f"User: {user_msg}\nAssistant: {ai_response}"
        importance, category = await memory_ranker.evaluate_and_categorize(exchange_text)

        # 3. Persist important memories to both stores
        if importance >= 0.4:
            memory_id = await long_term.insert_memory(
                content=exchange_text[:2000],
                category=category,
                importance=importance
            )
            if memory_id > 0:
                logger.info(
                    f"Saved long-term memory "
                    f"[ID:{memory_id} | Cat:{category} | Score:{importance:.2f}]"
                )
                # Also embed into the vector store for semantic retrieval
                from .semantic_memory import vector_store
                await vector_store.add_memory(
                    memory_id=memory_id,
                    text=exchange_text[:2000],
                    category=category,
                    importance=importance
                )
        else:
            logger.debug(f"Discarded low-importance exchange [Score:{importance:.2f}]")

    @classmethod
    async def retrieve_context(cls, query: str = "") -> str:
        """
        Build the memory context string to inject into the LLM prompt.
        Priority order:
          1. Semantic vector search (relevant regardless of age)
          2. Highest-ranked recent long-term memories (fallback)
          3. Short-term conversation buffer (always included)
        """
        context_parts = []

        # 1. Semantic search (most intelligent — finds relevant memories by meaning)
        if query:
            semantic_hits = await semantic_search(query, limit=3)
            if semantic_hits:
                context_parts.append("### Semantically Relevant Memories ###")
                for hit in semantic_hits:
                    context_parts.append(f"- {hit}")

        # 2. Fallback: top-ranked recent long-term memories (if semantic found nothing)
        if not context_parts:
            lt_mems = await long_term.retrieve_recent_memories(limit=3)
            if lt_mems:
                context_parts.append("### Relevant Long-Term Knowledge ###")
                for m in lt_mems:
                    context_parts.append(f"- [{m['category'].upper()}] {m['content']}")

        # 3. Short-term buffer (always appended for conversational continuity)
        st_mems = short_term.get_recent_context()
        if st_mems:
            context_parts.append("\n### Recent Conversation Context ###")
            for msg in st_mems:
                role = "FRIDAY" if msg["role"] == "assistant" else "SIR"
                context_parts.append(f"{role}: {msg['content']}")

        if not context_parts:
            return ""

        return "\n".join(context_parts)
