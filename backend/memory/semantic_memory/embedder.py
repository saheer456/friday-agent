"""
embedder.py — Lightweight FastEmbed singleton for FRIDAY.

Replaced sentence-transformers (torch) with fastembed (onnx) to stay
under the 512MB RAM limit on Render free tier.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import List

logger = logging.getLogger("Embedder")

# ── Singleton ─────────────────────────────────────────────────────────────────
_model = None
_model_ready = False

# ── Constants ─────────────────────────────────────────────────────────────────
# fastembed uses "BAAI/bge-small-en-v1.5" by default which is 384-dim (same as MiniLM)
# and extremely efficient.
MODEL_NAME = "BAAI/bge-small-en-v1.5"
CACHE_DIR  = Path(__file__).resolve().parent.parent.parent.parent / "data" / ".hf_cache"


def load_model_sync() -> None:
    """Blocking load — call once at startup."""
    global _model, _model_ready
    if _model_ready:
        return
    try:
        from fastembed import TextEmbedding
        
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        # Initialize model (downloads once if not present)
        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(CACHE_DIR))
        _model_ready = True
        
        logger.info(f"[Embedder] ✓ {MODEL_NAME} loaded via FastEmbed")
        print(f"[FRIDAY] ✓ Semantic embedder ready (FastEmbed)")
    except Exception as e:
        logger.error(f"[Embedder] Failed to load model: {e}")
        # Don't raise, just disable semantic features
        _model_ready = False


def is_ready() -> bool:
    return _model_ready


def _encode_sync(text: str) -> List[float]:
    if not _model_ready or _model is None:
        return []
    # fastembed returns a generator of numpy arrays
    embeddings = list(_model.embed([text]))
    if not embeddings:
        return []
    return embeddings[0].tolist()


async def embed_text(text: str) -> List[float]:
    """Async-safe wrapper."""
    if not _model_ready:
        return []
    return await asyncio.to_thread(_encode_sync, text)
