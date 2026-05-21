import aiosqlite
from pathlib import Path
from typing import List, Dict

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "memory_store.db"

async def init_chat_history_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await conn.commit()

async def save_chat_message(role: str, content: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            'INSERT INTO chat_history (role, content) VALUES (?, ?)',
            (role, content)
        )
        await conn.commit()

async def get_latest_chat_messages(limit: int = 20) -> List[Dict[str, str]]:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                'SELECT role, content FROM chat_history ORDER BY id DESC LIMIT ?',
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                results = [{"role": row["role"], "content": row["content"]} for row in rows]
                results.reverse()
                return results
    except Exception:
        return []

async def clear_chat_history() -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('DELETE FROM chat_history')
        await conn.commit()
