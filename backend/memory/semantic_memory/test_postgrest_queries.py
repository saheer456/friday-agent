import sys
import os
import asyncio
from pathlib import Path

ROOT = Path("c:/friday")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "friday-agent.env")

async def test_query(name, query_coro):
    try:
        res = await query_coro
        print(f"{name}: SUCCESS (count={len(res.data) if res.data else 0})")
        if res.data:
            print("  First row:", res.data[0])
    except Exception as e:
        print(f"{name}: FAILED - {e}")

async def main():
    from backend.supabase_client import get_client
    sb = await get_client()
    if not sb:
        print("No supabase client")
        return

    # 1. Simple select
    await test_query("1. Simple select", sb.table("file_chunks").select("filename, chunk_index").limit(2).execute())

    # 2. In filter with dot
    await test_query("2. In filter with dot", sb.table("file_chunks").select("filename, chunk_index").in_("filename", ["README.md"]).limit(2).execute())

    # 3. In filter with double quotes
    await test_query("3. In filter with double quotes", sb.table("file_chunks").select("filename, chunk_index").in_("filename", ['"README.md"']).limit(2).execute())

    # 4. Simple select + order
    await test_query("4. Simple select + order", sb.table("file_chunks").select("filename, chunk_index").order("chunk_index").limit(2).execute())

    # 5. In filter + lt + order (the full preview query)
    await test_query("5. In filter + lt + order", sb.table("file_chunks").select("filename, document, chunk_index").in_("filename", ["README.md"]).lt("chunk_index", 3).order("chunk_index").execute())

    # 6. In filter + lt + order with double quotes
    await test_query("6. In filter + lt + order with double quotes", sb.table("file_chunks").select("filename, document, chunk_index").in_("filename", ['"README.md"']).lt("chunk_index", 3).order("chunk_index").execute())

    # 7. match_memories RPC
    from backend.memory.semantic_memory import embedder
    if not embedder.is_ready():
        embedder.load_model_sync()
    qv = await embedder.embed_text("test memory")
    await test_query("7. match_memories RPC", sb.rpc("match_memories", {
        "query_embedding": qv,
        "match_threshold": 0.1,
        "match_count": 5
    }).execute())

    # 8. match_file_chunks RPC
    qv2 = await embedder.embed_text("What is FRIDAY")
    await test_query("8. match_file_chunks RPC", sb.rpc("match_file_chunks", {
        "query_embedding": qv2,
        "match_threshold": 0.1,
        "match_count": 5
    }).execute())

if __name__ == "__main__":
    asyncio.run(main())

