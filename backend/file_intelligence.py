"""
file_intelligence/ — Phase 4: File Ingestion & RAG Pipeline
============================================================
Supports: PDF, DOCX, TXT, CSV, JSON
Chunks text → embeds via MiniLM → stores in ChromaDB

NOTE: All third-party imports are done at MODULE LOAD TIME (top level) rather
than lazily inside parser functions.  Lazy imports inside asyncio.to_thread()
workers trigger filesystem scans from non-main threads, which causes
WinError 6714 (NTFS transaction conflict) when the project lives on OneDrive.
"""
import asyncio
import csv
import io
import json
import logging
from pathlib import Path
from typing import List, Dict

# ── Parser dependencies — imported once on the main thread ────────────────────
try:
    from pypdf import PdfReader as _PdfReader
    _PDF_OK = True
except ImportError:
    _PDF_OK = False
    logging.getLogger("FileIntelligence").warning("pypdf not installed — PDF upload disabled.")

try:
    from docx import Document as _DocxDocument
    _DOCX_OK = True
except ImportError:
    _DOCX_OK = False
    logging.getLogger("FileIntelligence").warning("python-docx not installed — DOCX upload disabled.")

logger = logging.getLogger("FileIntelligence")

# ── File Parsers ──────────────────────────────────────────────────────────────

def _parse_pdf(data: bytes) -> str:
    if not _PDF_OK:
        raise ValueError("pypdf is not installed. Run: pip install pypdf")
    reader = _PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)

def _parse_docx(data: bytes) -> str:
    if not _DOCX_OK:
        raise ValueError("python-docx is not installed. Run: pip install python-docx")
    doc = _DocxDocument(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

def _parse_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")

def _parse_csv(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = [", ".join(row) for row in reader]
    return "\n".join(rows)

def _parse_json(data: bytes) -> str:
    try:
        obj = json.loads(data.decode("utf-8", errors="replace"))
        return json.dumps(obj, indent=2)
    except Exception:
        return data.decode("utf-8", errors="replace")

PARSERS = {
    ".pdf":  _parse_pdf,
    ".docx": _parse_docx,
    ".txt":  _parse_txt,
    ".md":   _parse_txt,
    ".csv":  _parse_csv,
    ".json": _parse_json,
}


def extract_text(filename: str, data: bytes) -> str:
    """Parse raw file bytes into plain text based on extension."""
    ext = Path(filename).suffix.lower()
    parser = PARSERS.get(ext)
    if not parser:
        raise ValueError(f"Unsupported file type: {ext}")
    return parser(data)


# ── Chunking Engine ───────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 600, overlap: int = 100) -> List[str]:
    """
    Split text into overlapping chunks by word count.
    chunk_size: target words per chunk
    overlap: words repeated between consecutive chunks (prevents context breaks)
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap  # step back by overlap for continuity

    return chunks


# ── ChromaDB collection for files ─────────────────────────────────────────────

_file_collection = None
_chroma_lock = asyncio.Lock()

def _init_file_collection_sync():
    global _file_collection
    import chromadb
    from pathlib import Path as P
    chroma_path = P(__file__).resolve().parent.parent.parent / "data" / "chroma_db"
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    _file_collection = client.get_or_create_collection(
        name="friday_files",
        metadata={"hnsw:space": "cosine"}
    )

async def _ensure_collection():
    global _file_collection
    if _file_collection is None:
        await asyncio.to_thread(_init_file_collection_sync)


# ── Main ingest pipeline ──────────────────────────────────────────────────────

async def ingest_file(filename: str, data: bytes) -> Dict:
    """
    Full pipeline: parse → chunk → embed → store.
    Returns a summary dict with chunk count and filename.
    """
    from backend.memory.semantic_memory import embedder

    # 1. Parse
    try:
        text = await asyncio.to_thread(extract_text, filename, data)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    if not text.strip():
        return {"status": "error", "error": "File appears to be empty or unreadable."}

    # 2. Chunk
    chunks = chunk_text(text)
    if not chunks:
        return {"status": "error", "error": "Could not extract any text chunks."}

    # 3. Ensure embedder is ready
    if not embedder.is_ready():
        try:
            await asyncio.to_thread(embedder.load_model_sync)
        except Exception as e:
            return {"status": "error", "error": f"Semantic model failed to load: {e}"}

    if not embedder.is_ready():
        return {"status": "error", "error": "Semantic model unavailable. Please restart FRIDAY."}

    # 4. Embed and store all chunks
    await _ensure_collection()

    async def _store_chunk(i: int, chunk: str):
        vector = await embedder.embed_text(chunk)
        chunk_id = f"{filename}::chunk_{i}"
        def _upsert():
            _file_collection.upsert(
                ids=[chunk_id],
                embeddings=[vector],
                documents=[chunk],
                metadatas=[{"filename": filename, "chunk": i, "total_chunks": len(chunks)}]
            )
        async with _chroma_lock:
            await asyncio.to_thread(_upsert)

    # Process chunks concurrently (but throttled via lock)
    tasks = [_store_chunk(i, chunk) for i, chunk in enumerate(chunks)]
    await asyncio.gather(*tasks)

    logger.info(f"[FileIntelligence] Ingested '{filename}': {len(chunks)} chunks, ~{len(text.split())} words")
    return {
        "status":   "success",
        "filename": filename,
        "chunks":   len(chunks),
        "words":    len(text.split()),
    }


async def search_files(query: str, limit: int = 4) -> List[str]:
    """Semantic search over all ingested file chunks."""
    from backend.memory.semantic_memory import embedder

    await _ensure_collection()
    if _file_collection is None or not embedder.is_ready():
        return []

    try:
        query_vector = await embedder.embed_text(query)

        def _query():
            count = _file_collection.count()
            if count == 0:
                return None
            return _file_collection.query(
                query_embeddings=[query_vector],
                n_results=min(limit, count),
                include=["documents", "metadatas", "distances"]
            )

        async with _chroma_lock:
            results = await asyncio.to_thread(_query)

        if not results:
            return []

        docs      = results.get("documents", [[]])[0]
        distances = results.get("distances",  [[]])[0]
        metas     = results.get("metadatas",  [[]])[0]

        # Filter by similarity threshold (≥ 0.35)
        hits = [
            f"[From: {metas[i].get('filename','?')}]\n{docs[i]}"
            for i in range(len(docs))
            if (1.0 - distances[i]) >= 0.35
        ]
        return hits

    except Exception as e:
        logger.error(f"[FileIntelligence] search failed: {e}")
        return []
