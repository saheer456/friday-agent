"""
search.py
DuckDuckGo web search wrapper for real-time information retrieval.
"""
from duckduckgo_search import DDGS
import asyncio

async def web_search(query: str) -> str:
    """Performs a web search using DuckDuckGo and formats the top results."""
    try:
        def _search():
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=3))
            return results
        
        # Run synchronous DDGS search in a thread pool to avoid blocking async loop
        # 8-second timeout prevents DDG stalls from freezing the SSE stream
        try:
            results = await asyncio.wait_for(asyncio.to_thread(_search), timeout=8.0)
        except asyncio.TimeoutError:
            return "Web search timed out. Please try again in a moment."
        
        if not results:
            return "No results found."
            
        formatted_results = []
        for i, res in enumerate(results):
            formatted = f"Result {i+1}:\nTitle: {res.get('title', '')}\nSnippet: {res.get('body', '')}\nURL: {res.get('href', '')}"
            formatted_results.append(formatted)
            
        return "\n\n".join(formatted_results)
    except Exception as e:
        return f"Error performing web search: {str(e)}"
