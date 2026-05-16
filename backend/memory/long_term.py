from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Dict
from contextlib import asynccontextmanager

logger = logging.getLogger("LongTermMemory")

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "memory_store.db"

_db_conn = None


async def _sb_init() -> None:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        return
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
                "content": content,
                "category": category,
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


async def _sb_retrieve(limit: int = 50, offset: int = 0) -> List[Dict]:
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
            .range(offset, offset + limit - 1)
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


async def _sb_count() -> int:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        return 0
    try:
        res = await sb.table("memories").select("id", count="exact").execute()
        return res.count or 0
    except Exception as e:
        logger.error(f"[LongTermMemory] Supabase count failed: {e}")
        return 0


async def _get_sq_conn():
    global _db_conn
    import aiosqlite
    if _db_conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db_conn = await aiosqlite.connect(DB_PATH)
        _db_conn.row_factory = aiosqlite.Row
        await _db_conn.execute('''
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                importance REAL DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await _db_conn.commit()
    return _db_conn


async def _sq_init() -> None:
    conn = await _get_sq_conn()
    logger.info("[LongTermMemory] SQLite backend ready")


async def _sq_insert(content: str, category: str, importance: float) -> int:
    try:
        conn = await _get_sq_conn()
        cursor = await conn.execute(
            'INSERT INTO memories (content, category, importance) VALUES (?, ?, ?)',
            (content, category, importance)
        )
        await conn.commit()
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"[LongTermMemory] SQLite insert failed: {e}")
        return -1


async def _sq_retrieve(limit: int = 50, offset: int = 0) -> List[Dict]:
    try:
        conn = await _get_sq_conn()
        async with conn.execute(
            'SELECT * FROM memories ORDER BY importance DESC, created_at DESC LIMIT ? OFFSET ?',
            (limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"[LongTermMemory] SQLite retrieve failed: {e}")
        return []


async def _sq_delete(memory_id: int) -> bool:
    try:
        conn = await _get_sq_conn()
        await conn.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
        await conn.commit()
        return True
    except Exception as e:
        logger.error(f"[LongTermMemory] SQLite delete failed: {e}")
        return False


async def _sq_count() -> int:
    try:
        conn = await _get_sq_conn()
        async with conn.execute('SELECT COUNT(*) as cnt FROM memories') as cursor:
            row = await cursor.fetchone()
            return row["cnt"] if row else 0
    except Exception as e:
        logger.error(f"[LongTermMemory] SQLite count failed: {e}")
        return 0


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
        return await _sb_retrieve(limit=limit)
    return await _sq_retrieve(limit=limit)


async def list_memories(limit: int = 50, offset: int = 0) -> List[Dict]:
    if _use_supabase():
        return await _sb_retrieve(limit=limit, offset=offset)
    return await _sq_retrieve(limit=limit, offset=offset)


async def delete_memory(memory_id: int) -> bool:
    if _use_supabase():
        return await _sb_delete(memory_id)
    return await _sq_delete(memory_id)


async def count_memories() -> int:
    if _use_supabase():
        return await _sb_count()
    return await _sq_count()
