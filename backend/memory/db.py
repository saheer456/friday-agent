import os
import aiosqlite
import logging
from pathlib import Path

logger = logging.getLogger("Database")
DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "memory_store.db"
_db_conn = None

async def _get_sq_conn():
    global _db_conn
    if _db_conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db_conn = await aiosqlite.connect(DB_PATH)
        _db_conn.row_factory = aiosqlite.Row
        try:
            # Enable WAL mode for high concurrency
            await _db_conn.execute("PRAGMA journal_mode=WAL;")
            await _db_conn.commit()
            logger.info("SQLite journal_mode set to WAL")
        except Exception as e:
            logger.warning(f"Could not set SQLite journal_mode to WAL: {e}")
    return _db_conn
