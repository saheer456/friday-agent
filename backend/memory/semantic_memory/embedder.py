"""
embedder.py — HuggingFace MiniLM singleton for FRIDAY semantic memory.

Loads all-MiniLM-L6-v2 once at startup; stores weights in the project's
own data/.hf_cache so we avoid global user-cache permissions issues.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import List

logger = logging.getLogger("Embedder")

# ── Parser dependencies — imported once on the main thread ────────────────────
try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer
    _SENTENCE_TRANSFORMERS_OK = True
except ImportError:
    _SENTENCE_TRANSFORMERS_OK = False
    logger.warning("sentence-transformers not installed — semantic search disabled.")

# ── Constants ─────────────────────────────────────────────────────────────────
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
HF_CACHE   = Path(__file__).resolve().parent.parent.parent.parent / "data" / ".hf_cache"

# ── Singleton ─────────────────────────────────────────────────────────────────
_model = None
_model_ready = False

def load_model_sync() -> None:
    """Blocking load — call once from startup via run_in_executor."""
    global _model, _model_ready
    if _model_ready:
        return
    if not _SENTENCE_TRANSFORMERS_OK:
        raise RuntimeError("sentence-transformers is not installed. Run: pip install sentence-transformers")
    try:
        # Point HF to the project-local cache directory
        HF_CACHE.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(HF_CACHE))
        os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(HF_CACHE))

        _model = _SentenceTransformer(MODEL_NAME, cache_folder=str(HF_CACHE))
        _model_ready = True
        logger.info(f"[Embedder] ✓ {MODEL_NAME} loaded and ready.")
        print(f"[FRIDAY] ✓ Semantic embedder ready ({MODEL_NAME})")
    except Exception as e:
        logger.error(f"[Embedder] Failed to load model: {e}")
        raise


def is_ready() -> bool:
    return _model_ready


def _encode_sync(text: str) -> List[float]:
    if not _model_ready or _model is None:
        raise RuntimeError("Embedding model is not yet loaded.")
    vector = _model.encode(text, normalize_embeddings=True)
    return vector.tolist()


async def embed_text(text: str) -> List[float]:
    """Async-safe wrapper — runs the blocking encode() in a thread pool."""
    return await asyncio.to_thread(_encode_sync, text)
