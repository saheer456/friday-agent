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

async def main():
    from backend.supabase_client import get_client
    sb = await get_client()
    if not sb:
        print("No supabase client")
        return
        
    try:
        # Let's try select without order first
        res = await sb.table("file_chunks").select("*").limit(1).execute()
        print("Columns in file_chunks:")
        if res.data:
            print(res.data[0].keys())
        else:
            print("No data in file_chunks")
    except Exception as e:
        print("Select all failed:", e)

    try:
        # Let's try select chunk_index and order
        res = await sb.table("file_chunks").select("chunk_index").order("chunk_index", desc=False).limit(1).execute()
        print("Order chunk_index success:", res.data)
    except Exception as e:
        print("Order chunk_index failed:", e)

if __name__ == "__main__":
    asyncio.run(main())
