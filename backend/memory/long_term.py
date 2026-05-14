import aiosqlite
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger("LongTermMemory")

# Resolves to friday/data/memory_store.db
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "memory_store.db"

async def init_db() -> None:
    """Initialize the SQLite database schema."""
    try:
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
            logger.info("Long-term memory database initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize memory database: {e}")

async def insert_memory(content: str, category: str, importance: float) -> int:
    """Insert a new high-importance memory."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                'INSERT INTO memories (content, category, importance) VALUES (?, ?, ?)',
                (content, category, importance)
            )
            await db.commit()
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to insert memory: {e}")
        return -1

async def retrieve_recent_memories(limit: int = 5) -> List[Dict]:
    """Retrieve highly ranked recent memories."""
    try:
        # Get highest importance recent memories
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM memories ORDER BY importance DESC, created_at DESC LIMIT ?',
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to retrieve memories: {e}")
        return []

async def delete_memory(memory_id: int) -> bool:
    """Delete a specific memory by ID."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM memories WHERE id = ?', (memory_id,))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Failed to delete memory {memory_id}: {e}")
        return False
