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
        await _db_conn.execute('''
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                description TEXT
            )
        ''')
        await _db_conn.execute('''
            CREATE TABLE IF NOT EXISTS graph_edges (
                source TEXT,
                target TEXT,
                relation TEXT,
                weight REAL DEFAULT 1.0,
                PRIMARY KEY (source, target, relation),
                FOREIGN KEY (source) REFERENCES graph_nodes(id) ON DELETE CASCADE,
                FOREIGN KEY (target) REFERENCES graph_nodes(id) ON DELETE CASCADE
            )
        ''')
        await _db_conn.execute('CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source)')
        await _db_conn.execute('CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target)')
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


async def upsert_graph_node(node_id: str, name: str, node_type: str, description: str = "") -> None:
    if _use_supabase():
        try:
            from backend.supabase_client import get_client
            sb = await get_client()
            if sb is not None:
                await sb.table("graph_nodes").upsert({
                    "id": node_id,
                    "name": name,
                    "type": node_type,
                    "description": description
                }).execute()
                return
        except Exception as e:
            logger.warning(f"Supabase graph_nodes upsert failed: {e}. Falling back to SQLite.")

    try:
        conn = await _get_sq_conn()
        await conn.execute('''
            INSERT INTO graph_nodes (id, name, type, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                type=excluded.type,
                description=coalesce(nullif(excluded.description, ''), description)
        ''', (node_id, name, node_type, description))
        await conn.commit()
    except Exception as e:
        logger.error(f"SQLite upsert_graph_node failed: {e}")


async def add_graph_edge(source: str, target: str, relation: str, weight: float = 1.0) -> None:
    if _use_supabase():
        try:
            from backend.supabase_client import get_client
            sb = await get_client()
            if sb is not None:
                await sb.table("graph_edges").upsert({
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "weight": weight
                }).execute()
                return
        except Exception as e:
            logger.warning(f"Supabase graph_edges upsert failed: {e}. Falling back to SQLite.")

    try:
        conn = await _get_sq_conn()
        await conn.execute('''
            INSERT INTO graph_edges (source, target, relation, weight)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, target, relation) DO UPDATE SET
                weight=excluded.weight
        ''', (source, target, relation, weight))
        await conn.commit()
    except Exception as e:
        logger.error(f"SQLite add_graph_edge failed: {e}")


async def search_graph_nodes(query_term: str) -> List[Dict]:
    if _use_supabase():
        try:
            from backend.supabase_client import get_client
            sb = await get_client()
            if sb is not None:
                res = await sb.table("graph_nodes").select("*").ilike("name", f"%{query_term}%").limit(20).execute()
                return res.data or []
        except Exception as e:
            logger.warning(f"Supabase search_graph_nodes failed: {e}. Falling back to SQLite.")

    try:
        conn = await _get_sq_conn()
        async with conn.execute(
            "SELECT id, name, type, description FROM graph_nodes WHERE name LIKE ? OR description LIKE ? LIMIT 20",
            (f"%{query_term}%", f"%{query_term}%")
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"SQLite search_graph_nodes failed: {e}")
        return []


async def get_graph_neighbors(node_ids: List[str], depth: int = 1) -> Dict[str, List[Dict]]:
    if not node_ids:
        return {"nodes": [], "edges": []}

    if _use_supabase():
        try:
            from backend.supabase_client import get_client
            sb = await get_client()
            if sb is not None:
                res = await sb.table("graph_edges").select("source, target, relation, weight").in_("source", node_ids).execute()
                edges = res.data or []
                target_ids = list(set([e["target"] for e in edges] + [e["source"] for e in edges]))
                if target_ids:
                    nodes_res = await sb.table("graph_nodes").select("*").in_("id", target_ids).execute()
                    nodes = nodes_res.data or []
                else:
                    nodes = []
                return {"nodes": nodes, "edges": edges}
        except Exception as e:
            logger.warning(f"Supabase graph query failed: {e}. Falling back to SQLite.")

    try:
        conn = await _get_sq_conn()
        visited_nodes = set(node_ids)
        current_layer = set(node_ids)
        all_edges = []

        for _ in range(depth):
            if not current_layer:
                break
            placeholders = ",".join(["?"] * len(current_layer))
            query = f'''
                SELECT source, target, relation, weight 
                FROM graph_edges 
                WHERE source IN ({placeholders}) OR target IN ({placeholders})
            '''
            params = list(current_layer) + list(current_layer)
            async with conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                next_layer = set()
                for row in rows:
                    edge = dict(row)
                    all_edges.append(edge)
                    
                    src, tgt = edge["source"], edge["target"]
                    if src not in visited_nodes:
                        next_layer.add(src)
                        visited_nodes.add(src)
                    if tgt not in visited_nodes:
                        next_layer.add(tgt)
                        visited_nodes.add(tgt)
            current_layer = next_layer

        if visited_nodes:
            placeholders = ",".join(["?"] * len(visited_nodes))
            query = f'SELECT id, name, type, description FROM graph_nodes WHERE id IN ({placeholders})'
            async with conn.execute(query, list(visited_nodes)) as cursor:
                rows = await cursor.fetchall()
                nodes = [dict(row) for row in rows]
        else:
            nodes = []
            
        return {"nodes": nodes, "edges": all_edges}
    except Exception as e:
        logger.error(f"SQLite get_graph_neighbors failed: {e}")
        return {"nodes": [], "edges": []}
