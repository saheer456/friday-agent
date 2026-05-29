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

import logging
logging.basicConfig(level=logging.INFO)

async def test_pipeline():
    print("=== Phase 1: Database Initialization ===")
    from backend.memory.memory_manager import MemoryManager
    from backend.memory import long_term
    
    # Initialize DB (creates memories, graph_nodes, graph_edges tables)
    await MemoryManager.initialize()
    print("Database and collections initialized.")

    print("\n=== Phase 2: Manual Node/Edge Operations ===")
    # Insert node
    await long_term.upsert_graph_node("test_py", "Python language", "Technology", "A programming language used for scripting.")
    await long_term.upsert_graph_node("test_sqlite", "SQLite", "Technology", "A lightweight relational database.")
    # Add relationship edge
    await long_term.add_graph_edge("test_py", "test_sqlite", "COMPATIBLE_WITH", 0.95)
    
    # Verify retrieval
    results = await long_term.get_graph_neighbors(["test_py"], depth=1)
    print("Neighbors of test_py:")
    print("Nodes:", results["nodes"])
    print("Edges:", results["edges"])
    
    assert len(results["nodes"]) >= 2, "Should retrieve at least Python and SQLite nodes"
    assert len(results["edges"]) >= 1, "Should retrieve compatibility relation edge"
    print("✓ Manual nodes and edges inserted and retrieved successfully.")

    print("\n=== Phase 3: LLM Graph Extraction ===")
    from backend.memory.graph_extractor import extract_and_save_graph
    
    test_chat = (
        "User: Remember that Saheer Khan is the main developer of Friday. He loves using Python and prefers SQLite for storing local data.\n"
        "Assistant: Understood, sir. I have saved your preference that Saheer Khan developed Friday and prefers Python and SQLite."
    )
    
    success = await extract_and_save_graph(test_chat)
    if success:
        print("✓ LLM Graph extraction completed successfully.")
    else:
        print("✗ LLM Graph extraction failed.")
        return

    print("\n=== Phase 4: Hybrid Context Retrieval ===")
    # Query something that matches keywords
    query = "Who developed Friday and what database does he use?"
    context = await MemoryManager.retrieve_context(query)
    
    print("\nGenerated Retrieval Context:")
    print("-" * 50)
    print(context)
    print("-" * 50)
    
    assert "Relational Knowledge Graph Context" in context, "Should find graph context"
    assert "saheer" in context.lower(), "Should mention saheer"
    assert "sqlite" in context.lower(), "Should mention sqlite"
    print("✓ Hybrid GraphRAG retrieval returned correct linked facts.")
    print("\nALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_pipeline())
