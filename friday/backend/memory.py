"""
memory.py  —  mem0 graph memory layer for FRIDAY.

Uses:
  - LLM:     Groq (llama-3.1-8b-instant) — fast, cheap, runs inference
  - Embedder: HuggingFace all-MiniLM-L6-v2 — local, same model as ChromaDB
  - Store:   SQLite (local, no server) via mem0 default

Two public functions used by brain.py:
  save_memory(user_msg, ai_response)   → background thread, non-blocking
  recall_memory(query)                 → returns formatted string of relevant memories
"""

import os
import sys
import threading
from pathlib import Path

# ── mem0 singleton ────────────────────────────────────────────────────────────
_memory = None
_mem_lock = threading.Lock()

# User ID is fixed — single-user personal assistant
USER_ID = "sir"

MEM0_CONFIG = {
    "llm": {
        "provider": "groq",
        "config": {
            "model": "llama-3.1-8b-instant",
            "temperature": 0.1,
            "max_tokens": 100,
        },
    },
    "embedder": {
        "provider": "huggingface",
        "config": {
            # Same model already used by ChromaDB — no re-download needed
            "model": "sentence-transformers/all-MiniLM-L6-v2",
        },
    },
    # Store in the friday/data directory so it's alongside other local data
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "friday_mem0",
            "path": str(Path(__file__).resolve().parent.parent / "data" / "mem0_store"),
        },
    },
}


def _get_memory():
    """Lazy-load mem0 Memory singleton (thread-safe)."""
    global _memory
    if _memory is not None:
        return _memory
    with _mem_lock:
        if _memory is None:  # double-checked locking
            import io as _io
            _devnull = _io.StringIO()
            _old_out, _old_err = sys.stdout, sys.stderr
            try:
                sys.stdout, sys.stderr = _devnull, _devnull
                from mem0 import Memory
                _memory = Memory.from_config(MEM0_CONFIG)
            except Exception:
                _memory = None
            finally:
                sys.stdout, sys.stderr = _old_out, _old_err
    return _memory


# ── Public API ────────────────────────────────────────────────────────────────

def save_memory(user_msg: str, ai_response: str) -> None:
    """
    Extract and store memorable facts from this exchange.
    Runs in a background daemon thread — NEVER blocks the main response.
    mem0 handles deduplication automatically (won't store duplicates).
    """
    def _run():
        m = _get_memory()
        if m is None:
            return
        import io as _io
        _devnull = _io.StringIO()
        _old_out, _old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = _devnull, _devnull
            messages = [
                {"role": "user",      "content": user_msg[:150]},
                {"role": "assistant", "content": ai_response[:150]},
            ]
            m.add(messages, user_id=USER_ID)
        except Exception:
            pass
        finally:
            sys.stdout, sys.stderr = _old_out, _old_err

    threading.Thread(target=_run, daemon=True, name="friday-mem0-save").start()


def recall_memory(query: str, top_k: int = 5) -> str:
    """
    Retrieve the most relevant memories for a query.
    Returns a formatted string ready to inject into the system prompt.
    Returns empty string if mem0 is unavailable or nothing relevant found.
    """
    m = _get_memory()
    if m is None:
        return ""
    try:
        results = m.search(query, filters={"user_id": USER_ID}, limit=top_k)
        memories = results.get("results", []) if isinstance(results, dict) else results
        if not memories:
            return ""
        lines = [f"- {r['memory']}" for r in memories if r.get("memory")]
        return "\n".join(lines) if lines else ""
    except Exception as e:
        print(f"[Memory] recall error: {e}")
        return ""


def get_all_memories() -> list[dict]:
    """Return all stored memories (used by /api/memories endpoint)."""
    m = _get_memory()
    if m is None:
        return []
    try:
        results = m.get_all(filters={"user_id": USER_ID})
        memories = results.get("results", []) if isinstance(results, dict) else results
        return memories or []
    except Exception as e:
        print(f"[Memory] get_all error: {e}")
        return []


def delete_memory(memory_id: str) -> bool:
    """Delete a specific memory by ID."""
    m = _get_memory()
    if m is None:
        return False
    try:
        m.delete(memory_id=memory_id)
        return True
    except Exception as e:
        print(f"[Memory] delete error: {e}")
        return False
