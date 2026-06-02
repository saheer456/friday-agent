"""
chat_history.py — Session & message persistence.

Dual backend: Supabase (when SUPABASE_URL + SUPABASE_KEY are set)
              or SQLite (local fallback, unchanged).
Mirrors the _sb_ / _sq_ pattern from long_term.py.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Dict, Optional

import uuid
import aiosqlite

logger = logging.getLogger("ChatHistory")

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "memory_store.db"

# ── Backend selection ─────────────────────────────────────────────────────────

def _use_supabase() -> bool:
    from backend.supabase_client import is_available
    return is_available()


# ── SQLite helpers (unchanged logic) ──────────────────────────────────────────

async def _sq_init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS session_files (
                session_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, filename),
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
        """)
        async with conn.execute("PRAGMA table_info(chat_history)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "session_id" not in columns:
            try:
                await conn.execute("ALTER TABLE chat_history ADD COLUMN session_id TEXT DEFAULT 'default-session';")
            except Exception:
                pass
        await conn.commit()

async def _sq_create_session(session_id: str, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT OR IGNORE INTO chat_sessions (id, title) VALUES (?, ?)", (session_id, title))
        await conn.commit()

async def _sq_get_sessions() -> List[Dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT id, title, created_at FROM chat_sessions ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
    except Exception:
        return []

async def _sq_delete_session(session_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
        await conn.execute("DELETE FROM session_files WHERE session_id = ?", (session_id,))
        await conn.commit()

async def _sq_update_session_title(session_id: str, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE chat_sessions SET title = ? WHERE id = ?", (title, session_id))
        await conn.commit()

async def _sq_save_message(session_id: str, role: str, content: str) -> None:
    await _sq_create_session(session_id, "New Chat")
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)", (session_id, role, content))
        await conn.commit()

async def _sq_get_messages(session_id: str, limit: int = 100, before_id: Optional[int] = None) -> List[Dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            if before_id:
                async with conn.execute(
                    "SELECT id, role, content, created_at FROM chat_history WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
                    (session_id, before_id, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            else:
                async with conn.execute(
                    "SELECT id, role, content, created_at FROM chat_history WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ) as cursor:
                    rows = await cursor.fetchall()
            results = [dict(r) for r in rows]
            results.reverse()
            return results
    except Exception:
        return []

async def _sq_get_message_count(session_id: str) -> int:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            async with conn.execute("SELECT COUNT(*) FROM chat_history WHERE session_id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
    except Exception:
        return 0

async def _sq_clear(session_id: Optional[str] = None) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        if session_id:
            await conn.execute("DELETE FROM chat_history WHERE session_id = ?", (session_id,))
            await conn.execute("DELETE FROM session_files WHERE session_id = ?", (session_id,))
        else:
            await conn.execute("DELETE FROM chat_history")
            await conn.execute("DELETE FROM session_files")
            await conn.execute("DELETE FROM chat_sessions")
        await conn.commit()

async def _sq_associate_file(session_id: str, filename: str) -> None:
    await _sq_create_session(session_id, "New Chat")
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("INSERT OR IGNORE INTO session_files (session_id, filename) VALUES (?, ?)", (session_id, filename))
        await conn.commit()

async def _sq_get_files(session_id: str) -> List[str]:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT filename FROM session_files WHERE session_id = ?", (session_id,)) as cursor:
                return [r["filename"] for r in await cursor.fetchall()]
    except Exception:
        return []

async def _sq_remove_file(session_id: str, filename: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM session_files WHERE session_id = ? AND filename = ?", (session_id, filename))
        await conn.commit()

async def _sq_search_sessions(query: str) -> List[Dict]:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT id, title, created_at FROM chat_sessions WHERE title LIKE ? ORDER BY created_at DESC LIMIT 50",
                (f"%{query}%",),
            ) as cursor:
                return [dict(r) for r in await cursor.fetchall()]
    except Exception:
        return []


# ── Supabase helpers ──────────────────────────────────────────────────────────

async def _sb_get_client():
    from backend.supabase_client import get_client
    return await get_client()


async def _sb_create_session(title: str, user_id: Optional[str] = None) -> str:
    sb = await _sb_get_client()
    if sb is None:
        raise RuntimeError("Supabase not available")
    payload: Dict = {"id": str(uuid.uuid4()), "title": title}
    if user_id:
        payload["user_id"] = user_id
    res = await sb.table("sessions").insert(payload).execute()
    return res.data[0]["id"] if res.data else ""


async def _sb_get_sessions(user_id: Optional[str] = None, search: Optional[str] = None, include_archived: bool = False) -> List[Dict]:
    sb = await _sb_get_client()
    if sb is None:
        return []
    try:
        query = sb.table("sessions").select("id, title, created_at, updated_at, message_count, is_archived").order("updated_at", desc=True)
        if user_id:
            query = query.eq("user_id", user_id)
        if search:
            query = query.ilike("title", f"%{search}%")
        if not include_archived:
            query = query.eq("is_archived", False)
        res = await query.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Supabase get_sessions failed: {e}")
        return []

async def _sb_delete_session(session_id: str) -> None:
    sb = await _sb_get_client()
    if sb is None:
        return
    try:
        await sb.table("sessions").delete().eq("id", session_id).execute()
    except Exception as e:
        logger.error(f"Supabase delete_session failed: {e}")

async def _sb_update_session_title(session_id: str, title: str) -> None:
    sb = await _sb_get_client()
    if sb is None:
        return
    try:
        await sb.table("sessions").update({"title": title}).eq("id", session_id).execute()
    except Exception as e:
        logger.error(f"Supabase update_session_title failed: {e}")

async def _sb_save_message(session_id: str, role: str, content: str) -> None:
    sb = await _sb_get_client()
    if sb is None:
        return
    try:
        await sb.table("messages").insert({"session_id": session_id, "role": role, "content": content}).execute()
    except Exception as e:
        logger.error(f"Supabase save_message failed: {e}")

async def _sb_get_messages(session_id: str, limit: int = 100, before_id: Optional[int] = None) -> List[Dict]:
    sb = await _sb_get_client()
    if sb is None:
        return []
    try:
        query = sb.table("messages").select("id, role, content, created_at").eq("session_id", session_id).order("id", asc=True).limit(limit)
        if before_id is not None:
            query = query.lt("id", before_id)
        res = await query.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Supabase get_messages failed: {e}")
        return []

async def _sb_get_message_count(session_id: str) -> int:
    sb = await _sb_get_client()
    if sb is None:
        return 0
    try:
        res = await sb.table("messages").select("id", count="exact").eq("session_id", session_id).execute()
        return res.count or 0
    except Exception as e:
        logger.error(f"Supabase get_message_count failed: {e}")
        return 0

async def _sb_clear(session_id: Optional[str] = None) -> None:
    sb = await _sb_get_client()
    if sb is None:
        return
    try:
        if session_id:
            await sb.table("messages").delete().eq("session_id", session_id).execute()
            await sb.table("session_files").delete().eq("session_id", session_id).execute()
        else:
            await sb.table("messages").delete().neq("id", 0).execute()
            await sb.table("session_files").delete().neq("session_id", "").execute()
            await sb.table("sessions").delete().neq("id", "").execute()
    except Exception as e:
        logger.error(f"Supabase clear failed: {e}")

async def _sb_associate_file(session_id: str, filename: str) -> None:
    sb = await _sb_get_client()
    if sb is None:
        return
    try:
        await sb.table("session_files").insert({"session_id": session_id, "filename": filename}).execute()
    except Exception as e:
        logger.error(f"Supabase associate_file failed: {e}")

async def _sb_get_files(session_id: str) -> List[str]:
    sb = await _sb_get_client()
    if sb is None:
        return []
    try:
        res = await sb.table("session_files").select("filename").eq("session_id", session_id).execute()
        return [r["filename"] for r in (res.data or [])]
    except Exception as e:
        logger.error(f"Supabase get_files failed: {e}")
        return []

async def _sb_remove_file(session_id: str, filename: str) -> None:
    sb = await _sb_get_client()
    if sb is None:
        return
    try:
        await sb.table("session_files").delete().eq("session_id", session_id).eq("filename", filename).execute()
    except Exception as e:
        logger.error(f"Supabase remove_file failed: {e}")

async def _sb_search_sessions(query: str, user_id: Optional[str] = None) -> List[Dict]:
    sb = await _sb_get_client()
    if sb is None:
        return []
    try:
        q = sb.table("sessions").select("id, title, created_at, updated_at, message_count").ilike("title", f"%{query}%").order("updated_at", desc=True).limit(50)
        if user_id:
            q = q.eq("user_id", user_id)
        res = await q.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"Supabase search_sessions failed: {e}")
        return []


# ── Public API (routes to Supabase or SQLite) ────────────────────────────────

async def init_chat_history_db() -> None:
    if _use_supabase():
        logger.info("[ChatHistory] Supabase backend ready")
        return
    await _sq_init()


async def create_session(title: str, session_id: Optional[str] = None, user_id: Optional[str] = None) -> str:
    """Create a new session. Returns the session ID (server-generated in Supabase mode)."""
    if _use_supabase():
        return await _sb_create_session(title, user_id=user_id)
    sid = session_id or f"session-{__import__('time').time_ns()}"
    await _sq_create_session(sid, title)
    return sid


async def get_sessions(user_id: Optional[str] = None, search: Optional[str] = None, include_archived: bool = False) -> List[Dict]:
    if _use_supabase():
        return await _sb_get_sessions(user_id=user_id, search=search, include_archived=include_archived)
    return await _sq_get_sessions()


async def delete_session(session_id: str) -> None:
    if _use_supabase():
        await _sb_delete_session(session_id)
    await _sq_delete_session(session_id)


async def update_session_title(session_id: str, title: str) -> None:
    if _use_supabase():
        await _sb_update_session_title(session_id, title)
    await _sq_update_session_title(session_id, title)


async def save_chat_message(session_id: str, role: str, content: str) -> None:
    if _use_supabase():
        await _sb_save_message(session_id, role, content)
    await _sq_save_message(session_id, role, content)


async def get_latest_chat_messages(session_id: str, limit: int = 100, before_id: Optional[int] = None) -> List[Dict]:
    if _use_supabase():
        return await _sb_get_messages(session_id, limit=limit, before_id=before_id)
    return await _sq_get_messages(session_id, limit=limit, before_id=before_id)


async def get_message_count(session_id: str) -> int:
    if _use_supabase():
        return await _sb_get_message_count(session_id)
    return await _sq_get_message_count(session_id)


async def clear_chat_history(session_id: Optional[str] = None) -> None:
    if _use_supabase():
        await _sb_clear(session_id=session_id)
    await _sq_clear(session_id=session_id)


async def associate_file_with_session(session_id: str, filename: str) -> None:
    if _use_supabase():
        await _sb_associate_file(session_id, filename)
    await _sq_associate_file(session_id, filename)


async def get_session_files(session_id: str) -> List[str]:
    if _use_supabase():
        return await _sb_get_files(session_id)
    return await _sq_get_files(session_id)


async def remove_file_from_session(session_id: str, filename: str) -> None:
    if _use_supabase():
        await _sb_remove_file(session_id, filename)
    await _sq_remove_file(session_id, filename)


async def search_sessions(query: str, user_id: Optional[str] = None) -> List[Dict]:
    """Full-text search across session titles."""
    if _use_supabase():
        return await _sb_search_sessions(query, user_id=user_id)
    return await _sq_search_sessions(query)
