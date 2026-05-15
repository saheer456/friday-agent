"""
long_term.py — Long-term memory persistence.

Storage strategy (auto-detected at runtime):
  - SUPABASE_URL + SUPABASE_KEY set  →  Supabase PostgreSQL  (production)
  - Otherwise                         →  local aiosqlite/SQLite (dev)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger("LongTermMemory")

# Local SQLite path (fallback for dev)
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "memory_store.db"


# ── Supabase backend ──────────────────────────────────────────────────────────

async def _sb_init() -> None:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        return
    # Table is created via Supabase SQL editor — nothing to do here
    logger.info("[LongTermMemory] Supabase backend ready")


async def _sb_insert(content: str, category: str, importance: float) -> int:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        return -1
    try:
        res = (
            await sb.table("memories")
            .insert({
                "content":    content,
                "category":   category,
                "importance": importance,
            })
            .execute()
        )
        data = res.data
        if data:
            return data[0].get("id", -1)
    except Exception as e:
        logger.error(f"[LongTermMemory] Supabase insert failed: {e}")
    return -1


async def _sb_retrieve(limit: int) -> List[Dict]:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        return []
    try:
        res = (
            await sb.table("memories")
            .select("*")
            .order("importance", desc=True)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"[LongTermMemory] Supabase retrieve failed: {e}")
        return []


async def _sb_delete(memory_id: int) -> bool:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        return False
    try:
        await sb.table("memories").delete().eq("id", memory_id).execute()
        return True
    except Exception as e:
        logger.error(f"[LongTermMemory] Supabase delete failed: {e}")
        return False


# ── SQLite fallback backend ───────────────────────────────────────────────────

async def _sq_init() -> None:
    import aiosqlite
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()
    logger.info("[LongTermMemory] SQLite backend ready")


async def _sq_insert(content: str, category: str, importance: float) -> int:
    import aiosqlite
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                'INSERT INTO memories (content, category, importance) VALUES (?, ?, ?)',
                (content, category, importance)
            )
            await db.commit()
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"[LongTermMemory] SQLite insert failed: {e}")
        return -1


async def _sq_retrieve(limit: int) -> List[Dict]:
    import aiosqlite
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM memories ORDER BY importance DESC, created_at DESC LIMIT ?',
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"[LongTermMemory] SQLite retrieve failed: {e}")
        return []


async def _sq_delete(memory_id: int) -> bool:
    import aiosqlite
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"[LongTermMemory] SQLite delete failed: {e}")
        return False


# ── Public API (auto-selects backend) ────────────────────────────────────────

def _use_supabase() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))


async def init_db() -> None:
    if _use_supabase():
        await _sb_init()
    else:
        await _sq_init()


async def insert_memory(content: str, category: str, importance: float) -> int:
    if _use_supabase():
        return await _sb_insert(content, category, importance)
    return await _sq_insert(content, category, importance)


async def retrieve_recent_memories(limit: int = 5) -> List[Dict]:
    if _use_supabase():
        return await _sb_retrieve(limit)
    return await _sq_retrieve(limit)


async def delete_memory(memory_id: int) -> bool:
    if _use_supabase():
        return await _sb_delete(memory_id)
    return await _sq_delete(memory_id)
