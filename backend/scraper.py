"""
scraper.py
Web scraping using httpx, BeautifulSoup4, and readability-lxml.
"""
import httpx
from bs4 import BeautifulSoup
from readability import Document
import asyncio

async def scrape_url(url: str) -> str:
    """Fetches and extracts the main readable content from a URL."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()
            
        doc = Document(response.text)
        summary_html = doc.summary()
        
        # Parse with BeautifulSoup to strip HTML tags from the readability output
        soup = BeautifulSoup(summary_html, "html.parser")
        
        # Strip scripts and styles just in case
        for script in soup(["script", "style"]):
            script.extract()
            
        text = soup.get_text(separator="\n", strip=True)
        
        # Truncate to 3000 chars to avoid overflowing the LLM context
        if len(text) > 3000:
            text = text[:3000] + "... [Content Truncated]"
            
        return f"Scraped content from {url}:\n{text}"
    except httpx.TimeoutException:
        return f"Failed to scrape {url}: Connection timed out."
    except Exception as e:
        return f"Failed to scrape {url}: {str(e)}"
