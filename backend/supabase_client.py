"""
supabase_client.py — Singleton async Supabase client for FRIDAY.

Falls back gracefully if SUPABASE_URL / SUPABASE_KEY are not set
(local dev without Supabase configured).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("SupabaseClient")

_client = None
_unavailable = False   # set True once we confirm env vars are missing


async def get_client():
    """Return the shared async Supabase client, or None if not configured."""
    global _client, _unavailable

    if _unavailable:
        return None

    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()

    if not url or not key:
        logger.warning(
            "[Supabase] SUPABASE_URL or SUPABASE_KEY not set — "
            "falling back to local SQLite/ChromaDB storage."
        )
        _unavailable = True
        return None

    try:
        from supabase import acreate_client
        _client = await acreate_client(url, key)
        logger.info(f"[Supabase] ✓ Connected to {url}")
        return _client
    except Exception as e:
        logger.error(f"[Supabase] Connection failed: {e}")
        _unavailable = True
        return None


def is_available() -> bool:
    """Quick sync check — True if client is already connected."""
    return _client is not None
