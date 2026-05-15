import traceback
try:
    from backend import rag
    print("rag loaded")
    from backend import search
    print("search loaded")
    from backend import scraper
    print("scraper loaded")
    from backend import tools
    print("tools loaded")
    from backend.memory import MemoryManager
    print("MemoryManager loaded")
    from backend import tool_bridge
    print("tool_bridge loaded")
except Exception:
    traceback.print_exc()
