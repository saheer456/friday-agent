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
import threading
from pathlib import Path
import queue

# ── mem0 singleton ────────────────────────────────────────────────────────────
_memory = None
_mem_lock = threading.Lock()    # guards the _memory singleton only
_worker_lock = threading.Lock() # guards worker startup only (separate to avoid deadlock)
_memory_ready = threading.Event() # set ONLY after the HF model is fully loaded
_chroma_lock = threading.Lock()   # serialises ALL ChromaDB ops (reads + writes)

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


def _memory_enabled() -> bool:
    raw = (os.getenv("FRIDAY_ENABLE_MEMORY", "1") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _ensure_local_hf_cache() -> None:
    """
    Keep Hugging Face caches inside the project to avoid Windows permission
    issues with global user cache directories.
    """
    base = Path(__file__).resolve().parent.parent / "data" / ".hf_cache"
    hub = base / "hub"
    transformers = base / "transformers"
    try:
        hub.mkdir(parents=True, exist_ok=True)
        transformers.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    os.environ.setdefault("HF_HOME", str(base))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(hub))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(transformers))


def _get_memory():
    """
    Return the already-loaded mem0 singleton, or None if not yet ready.
    Does NOT trigger loading — call warm_up() for that.
    This keeps recall_memory() safe to call at any time without blocking.
    """
    return _memory if _memory_ready.is_set() else None


def warm_up() -> None:
    """
    Load the mem0 Memory singleton (HuggingFace model + ChromaDB).
    Intended to be called ONCE from the server startup warmup thread.
    Sets _memory_ready when done so recall_memory() can start working.
    """
    global _memory
    if not _memory_enabled():
        return
    with _mem_lock:
        if not _memory_ready.is_set():
            try:
                _ensure_local_hf_cache()
                from mem0 import Memory
                _memory = Memory.from_config(MEM0_CONFIG)
                _memory_ready.set()   # ← signal that recall_memory can now run
                print("[FRIDAY] ✓ Memory warmed up")
            except Exception as e:
                print(f"[FRIDAY] Memory warmup failed: {e}")
                _memory = None        # stays None; recall_memory returns "" safely


# ── Public API ────────────────────────────────────────────────────────────────

_save_queue = queue.Queue()
_worker_started = False

def _memory_worker():
    """Single background thread that serialises all ChromaDB writes."""
    while True:
        try:
            item = _save_queue.get()
            if item is None:
                _save_queue.task_done()
                break
            user_msg, ai_response = item
            # _get_memory() only acquires _mem_lock briefly for singleton init.
            # By this point the singleton is already loaded, so no contention.
            m = _memory
            if m is not None:
                try:
                    messages = [
                        {"role": "user",      "content": user_msg[:150]},
                        {"role": "assistant", "content": ai_response[:150]},
                    ]
                    with _chroma_lock:  # ← holds lock for the entire write
                        m.add(messages, user_id=USER_ID)
                except Exception as e:
                    print(f"[Memory] save error: {e}")
            _save_queue.task_done()
        except Exception as e:
            print(f"[Memory] worker error: {e}")

def save_memory(user_msg: str, ai_response: str) -> None:
    """
    Extract and store memorable facts from this exchange.
    Enqueues to a single background worker — never blocks the event loop.
    Uses _worker_lock (NOT _mem_lock) so it cannot deadlock with recall_memory.
    """
    global _worker_started
    # Use _worker_lock here — completely separate from _mem_lock.
    # This prevents the deadlock where save held _mem_lock while recall
    # tried to acquire _mem_lock inside _get_memory().
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_memory_worker, daemon=True, name="friday-mem0-worker").start()
            _worker_started = True
    _save_queue.put((user_msg, ai_response))


def recall_memory(query: str, top_k: int = 3) -> str:
    """
    Retrieve the most relevant memories for a query.
    Returns empty string immediately if the model isn't warmed up yet —
    this prevents any chat request from triggering a slow HF model load.
    """
    # Non-blocking readiness check — returns "" instantly if warm_up() hasn't
    # completed yet. This is the key fix for the second-message hang.
    if not _memory_ready.is_set():
        return ""

    m = _memory  # safe: _memory_ready guarantees it's set and not None
    if m is None:
        return ""

    try:
        # Non-blocking lock with timeout — if worker holds the lock (doing m.add),
        # skip memory for this turn instead of freezing the SSE stream.
        acquired = _chroma_lock.acquire(timeout=3.0)
        if not acquired:
            print("[Memory] recall skipped — ChromaDB busy with write")
            return ""
        try:
            results = m.search(query, filters={"user_id": USER_ID}, limit=top_k)
        finally:
            _chroma_lock.release()
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
