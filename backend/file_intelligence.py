"""
file_intelligence.py — File ingestion & RAG pipeline.

Supports: PDF, DOCX, TXT, CSV, JSON
Chunks text → embeds via MiniLM → stores in:
  - Supabase pgvector (production)
  - ChromaDB          (local dev fallback)
"""
import asyncio
import csv
import io
import json
import logging
import os
from pathlib import Path
from typing import List, Dict

# ── Parser dependencies ───────────────────────────────────────────────────────
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
        raise ValueError("pypdf is not installed.")
    reader = _PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)

def _parse_docx(data: bytes) -> str:
    if not _DOCX_OK:
        raise ValueError("python-docx is not installed.")
    doc = _DocxDocument(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

def _parse_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")

def _parse_csv(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return "\n".join(", ".join(row) for row in reader)

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
    ext = Path(filename).suffix.lower()
    parser = PARSERS.get(ext)
    if not parser:
        raise ValueError(f"Unsupported file type: {ext}")
    return parser(data)


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 600, overlap: int = 100) -> List[str]:
    words = text.split()
    if not words:
        return []
    chunks, start = [], 0
    step = max(1, chunk_size - overlap)
    while start < len(words):
        chunks.append(" ".join(words[start:start + chunk_size]))
        start += step
    return chunks


# ── Storage helpers ───────────────────────────────────────────────────────────

def _use_supabase() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY"))

# ChromaDB singletons (local fallback)
_file_collection = None
_chroma_lock = asyncio.Lock()

def _init_file_collection_sync():
    global _file_collection
    import chromadb
    chroma_path = Path(__file__).resolve().parent.parent.parent / "data" / "chroma_db"
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    _file_collection = client.get_or_create_collection(
        name="friday_files",
        metadata={"hnsw:space": "cosine"},
    )

async def _ensure_chroma():
    global _file_collection
    if _file_collection is None:
        await asyncio.to_thread(_init_file_collection_sync)


# ── Main ingest pipeline ──────────────────────────────────────────────────────

async def ingest_file(filename: str, data: bytes) -> Dict:
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
            return {"status": "error", "error": f"Embedding model failed to load: {e}"}

    # 4. Embed and store
    if _use_supabase():
        await _ingest_supabase(filename, chunks, embedder)
    else:
        await _ingest_chroma(filename, chunks, embedder)

    logger.info(f"[FileIntelligence] Ingested '{filename}': {len(chunks)} chunks, ~{len(text.split())} words")
    return {
        "status":   "success",
        "filename": filename,
        "chunks":   len(chunks),
        "words":    len(text.split()),
    }


async def _ingest_supabase(filename: str, chunks: List[str], embedder) -> None:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        logger.warning("[FileIntelligence] Supabase unavailable — skipping store")
        return

    rows = []
    for i, chunk in enumerate(chunks):
        vector = await embedder.embed_text(chunk)
        rows.append({
            "id":           f"{filename}::chunk_{i}",
            "embedding":    vector,
            "document":     chunk,
            "filename":     filename,
            "chunk_index":  i,
            "total_chunks": len(chunks),
        })

    try:
        await sb.table("file_chunks").upsert(rows).execute()
    except Exception as e:
        logger.error(f"[FileIntelligence] Supabase upsert failed: {e}")


async def _ingest_chroma(filename: str, chunks: List[str], embedder) -> None:
    await _ensure_chroma()

    async def _store_chunk(i: int, chunk: str):
        vector = await embedder.embed_text(chunk)
        chunk_id = f"{filename}::chunk_{i}"
        def _upsert():
            _file_collection.upsert(
                ids=[chunk_id],
                embeddings=[vector],
                documents=[chunk],
                metadatas=[{"filename": filename, "chunk": i, "total_chunks": len(chunks)}],
            )
        async with _chroma_lock:
            await asyncio.to_thread(_upsert)

    await asyncio.gather(*[_store_chunk(i, c) for i, c in enumerate(chunks)])


# ── Search ────────────────────────────────────────────────────────────────────

async def search_files(query: str, limit: int = 4) -> List[str]:
    from backend.memory.semantic_memory import embedder

    if not embedder.is_ready():
        return []

    query_vector = await embedder.embed_text(query)

    if _use_supabase():
        return await _search_supabase(query_vector, limit)
    return await _search_chroma(query_vector, limit)


async def _search_supabase(query_vector: List[float], limit: int) -> List[str]:
    from backend.supabase_client import get_client
    sb = await get_client()
    if sb is None:
        return []
    try:
        res = await sb.rpc(
            "match_file_chunks",
            {
                "query_embedding": query_vector,
                "match_threshold": 0.35,
                "match_count":     limit,
            },
        ).execute()
        return [
            f"[From: {r.get('filename', '?')}]\n{r.get('document', '')}"
            for r in (res.data or [])
        ]
    except Exception as e:
        logger.error(f"[FileIntelligence] Supabase search failed: {e}")
        return []


async def _search_chroma(query_vector: List[float], limit: int) -> List[str]:
    await _ensure_chroma()
    if _file_collection is None:
        return []
    try:
        def _query():
            count = _file_collection.count()
            if count == 0:
                return None
            return _file_collection.query(
                query_embeddings=[query_vector],
                n_results=min(limit, count),
                include=["documents", "metadatas", "distances"],
            )

        async with _chroma_lock:
            results = await asyncio.to_thread(_query)

        if not results:
            return []

        docs      = results.get("documents", [[]])[0]
        distances = results.get("distances",  [[]])[0]
        metas     = results.get("metadatas",  [[]])[0]

        return [
            f"[From: {metas[i].get('filename','?')}]\n{docs[i]}"
            for i in range(len(docs))
            if (1.0 - distances[i]) >= 0.35
        ]
    except Exception as e:
        logger.error(f"[FileIntelligence] ChromaDB search failed: {e}")
        return []
