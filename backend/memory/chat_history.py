import aiosqlite
from pathlib import Path
from typing import List, Dict

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "memory_store.db"

async def init_chat_history_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        # Create chat_sessions table
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Create chat_history table with session_id
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
        ''')
        # Create session_files table to link PDFs to a specific session
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS session_files (
                session_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, filename),
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
        ''')
        
        # Check and migrate columns of chat_history if needed
        async with conn.execute("PRAGMA table_info(chat_history)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "session_id" not in columns:
            try:
                await conn.execute("ALTER TABLE chat_history ADD COLUMN session_id TEXT DEFAULT 'default-session';")
            except Exception:
                pass
                
        await conn.commit()

# Session Management Operations
async def create_session(session_id: str, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            'INSERT OR IGNORE INTO chat_sessions (id, title) VALUES (?, ?)',
            (session_id, title)
        )
        await conn.commit()

async def get_sessions() -> List[Dict[str, str]]:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                'SELECT id, title, created_at FROM chat_sessions ORDER BY created_at DESC'
            ) as cursor:
                rows = await cursor.fetchall()
                return [{"id": row["id"], "title": row["title"], "created_at": row["created_at"]} for row in rows]
    except Exception:
        return []

async def delete_session(session_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute('DELETE FROM chat_sessions WHERE id = ?', (session_id,))
        # Also clean up the files association
        await conn.execute('DELETE FROM session_files WHERE session_id = ?', (session_id,))
        await conn.commit()

async def update_session_title(session_id: str, title: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            'UPDATE chat_sessions SET title = ? WHERE id = ?',
            (title, session_id)
        )
        await conn.commit()

# Session-specific Message Operations
async def save_chat_message(session_id: str, role: str, content: str) -> None:
    # Ensure session exists first
    await create_session(session_id, "New Chat")
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            'INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)',
            (session_id, role, content)
        )
        await conn.commit()

async def get_latest_chat_messages(session_id: str, limit: int = 20) -> List[Dict[str, str]]:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                'SELECT role, content FROM chat_history WHERE session_id = ? ORDER BY id DESC LIMIT ?',
                (session_id, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                results = [{"role": row["role"], "content": row["content"]} for row in rows]
                results.reverse()
                return results
    except Exception:
        return []

async def clear_chat_history(session_id: str = None) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        if session_id:
            await conn.execute('DELETE FROM chat_history WHERE session_id = ?', (session_id,))
            await conn.execute('DELETE FROM session_files WHERE session_id = ?', (session_id,))
        else:
            await conn.execute('DELETE FROM chat_history')
            await conn.execute('DELETE FROM session_files')
            await conn.execute('DELETE FROM chat_sessions')
        await conn.commit()

# Session-specific File Associations
async def associate_file_with_session(session_id: str, filename: str) -> None:
    # Ensure session exists first
    await create_session(session_id, "New Chat")
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            'INSERT OR IGNORE INTO session_files (session_id, filename) VALUES (?, ?)',
            (session_id, filename)
        )
        await conn.commit()

async def get_session_files(session_id: str) -> List[str]:
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                'SELECT filename FROM session_files WHERE session_id = ?',
                (session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [row["filename"] for row in rows]
    except Exception:
        return []

async def remove_file_from_session(session_id: str, filename: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            'DELETE FROM session_files WHERE session_id = ? AND filename = ?',
            (session_id, filename)
        )
        await conn.commit()

