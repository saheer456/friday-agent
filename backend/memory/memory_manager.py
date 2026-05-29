import asyncio
import logging
import re
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
        from . import chat_history
        await chat_history.init_chat_history_db()
        short_term.clear_buffer()
        # Fire up the semantic layer in the background (FastEmbed model loading is deferred to a background task)
        asyncio.create_task(_sem_initialize())

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
        importance, category = memory_ranker.evaluate_and_categorize(exchange_text)

        # 3. Persist important memories to both stores
        import os
        min_importance = float(os.getenv("FRIDAY_MEMORY_MIN_IMPORTANCE", "0.4"))
        if importance >= min_importance:
            # Similarity pre-check to prevent duplicate memory creation
            try:
                from .semantic_memory import embedder, vector_store
                if embedder.is_ready() and vector_store.is_ready():
                    query_vector = await embedder.embed_text(user_msg)
                    hits = await vector_store.search_memories(query_vector, limit=1)
                    if hits and hits[0].get("score", 0.0) >= 0.85:
                        logger.info(f"Discarding duplicate memory (similarity: {hits[0]['score']:.2f})")
                        return
            except Exception as e:
                logger.error(f"Failed memory duplicate check: {e}")

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
                # Trigger background graph extraction asynchronously
                try:
                    from .graph_extractor import extract_and_save_graph
                    asyncio.create_task(extract_and_save_graph(exchange_text))
                except Exception as ge_err:
                    logger.error(f"Failed to start background graph extraction: {ge_err}")
        else:
            logger.debug(f"Discarded low-importance exchange [Score:{importance:.2f}]")

    @classmethod
    async def retrieve_context(cls, query: str = "") -> str:
        """
        Build the memory context string to inject into the LLM prompt.
        Priority order:
          1. Relational Knowledge Graph Context (structured relationships)
          2. Semantic vector search (relevant regardless of age)
          3. Highest-ranked recent long-term memories (fallback)
          4. Short-term conversation buffer (always included)
        """
        context_parts = []

        # 1. Relational Knowledge Graph Context
        if query:
            try:
                # Tokenize and extract keywords (length >= 3, excluding common stop words)
                tokens = re.findall(r'\b\w{3,}\b', query.lower())
                stop_words = {"the", "and", "for", "with", "what", "how", "why", "who", "where", "can", "you", "does", "that", "this"}
                keywords = [t for t in tokens if t not in stop_words]
                
                matched_ids = []
                for kw in keywords:
                    nodes = await long_term.search_graph_nodes(kw)
                    for n in nodes:
                        matched_ids.append(n["id"])
                
                # Fetch 1-hop connections
                if matched_ids:
                    graph_data = await long_term.get_graph_neighbors(list(set(matched_ids)), depth=1)
                    edges = graph_data.get("edges", [])
                    nodes = graph_data.get("nodes", [])
                    
                    graph_lines = []
                    for edge in edges:
                        src = edge.get("source", "")
                        tgt = edge.get("target", "")
                        rel = edge.get("relation", "")
                        graph_lines.append(f"- {src} --[{rel}]--> {tgt}")
                        
                    node_desc_lines = []
                    for node in nodes:
                        if node.get("description"):
                            node_desc_lines.append(f"- {node['name']} ({node['type']}): {node['description']}")
                            
                    if graph_lines or node_desc_lines:
                        context_parts.append("### Relational Knowledge Graph Context ###")
                        if graph_lines:
                            context_parts.append("Relationships:")
                            context_parts.extend(graph_lines)
                        if node_desc_lines:
                            context_parts.append("Entity Details:")
                            context_parts.extend(node_desc_lines)
                        context_parts.append("")  # Empty line for formatting separator
            except Exception as graph_err:
                logger.error(f"Error retrieving graph context: {graph_err}")

        # 2. Semantic search (most intelligent — finds relevant memories by meaning)
        if query:
            semantic_hits = await semantic_search(query, limit=3)
            if semantic_hits:
                context_parts.append("### Semantically Relevant Memories ###")
                for hit in semantic_hits:
                    context_parts.append(f"- {hit}")

        # 3. Fallback: top-ranked recent long-term memories (if semantic found nothing)
        if not context_parts:
            lt_mems = await long_term.retrieve_recent_memories(limit=3)
            if lt_mems:
                context_parts.append("### Relevant Long-Term Knowledge ###")
                for m in lt_mems:
                    context_parts.append(f"- [{m['category'].upper()}] {m['content']}")

        # 4. Short-term buffer (always appended for conversational continuity)
        st_mems = short_term.get_recent_context()
        if st_mems:
            context_parts.append("\n### Recent Conversation Context ###")
            for msg in st_mems:
                role = "FRIDAY" if msg["role"] == "assistant" else "SIR"
                context_parts.append(f"{role}: {msg['content']}")

        if not context_parts:
            return ""

        return "\n".join(context_parts)
