"""
rag.py
Document ingestion and RAG using LangChain + ChromaDB.
Embeddings: HuggingFace all-MiniLM-L6-v2 (local, no Ollama needed, ~90MB one-time download).

All heavy imports are deferred inside functions so `import rag` is near-instant.
"""
import os
import hashlib
from pathlib import Path
# NOTE: LangChain / HuggingFace / ChromaDB imports are LAZY (inside functions)
#       to keep startup time near-zero.

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).resolve().parent.parent
DATA_DIR        = BASE_DIR / "data"
VECTORSTORE_DIR = BASE_DIR / "vectorstore"
HASH_LOG        = VECTORSTORE_DIR / "ingested_hashes.txt"

SUPPORTED = {".txt", ".md", ".pdf", ".docx"}

# ── Embeddings (lazy-loaded — downloaded once to HF cache, then fully offline) ─
_embeddings = None

def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        from langchain_huggingface import HuggingFaceEmbeddings  # lazy import
        print("Loading embedding model (first run downloads ~90 MB)…")
        _embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        print("Embedding model ready.")
    return _embeddings


# ── ChromaDB helpers ─────────────────────────────────────────────────────────
_vs_instance = None  # singleton — avoid reopening the SQLite file on every search

def _vectorstore():
    global _vs_instance
    if _vs_instance is None:
        from langchain_chroma import Chroma  # lazy import
        os.makedirs(VECTORSTORE_DIR, exist_ok=True)
        _vs_instance = Chroma(persist_directory=str(VECTORSTORE_DIR), embedding_function=_get_embeddings())
    return _vs_instance


def _get_hashes() -> set:
    if not HASH_LOG.exists():
        return set()
    return {l.strip() for l in HASH_LOG.read_text().splitlines() if l.strip()}


def _save_hash(h: str):
    os.makedirs(VECTORSTORE_DIR, exist_ok=True)
    with open(HASH_LOG, "a") as f:
        f.write(h + "\n")


def _file_hash(path: str) -> str:
    """Stream file in 64 KB chunks to avoid loading large files into RAM."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Ingestion ─────────────────────────────────────────────────────────────────
def ingest_files():
    """Scan data/ and ingest any new documents into ChromaDB (skips duplicates)."""
    from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader  # lazy
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # lazy
    os.makedirs(DATA_DIR, exist_ok=True)
    vs      = _vectorstore()
    hashes  = _get_hashes()
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=60)
    new_docs = []
    hashes_to_save = []  # accumulate; only write after successful add_documents

    for fp in DATA_DIR.glob("**/*"):
        if not fp.is_file() or fp.suffix.lower() not in SUPPORTED:
            continue

        fh = _file_hash(str(fp))
        if fh in hashes:
            continue

        print(f"Ingesting: {fp.name}")
        try:
            if fp.suffix.lower() in {".txt", ".md"}:
                loader = TextLoader(str(fp), encoding="utf-8")
            elif fp.suffix.lower() == ".pdf":
                loader = PyPDFLoader(str(fp))
            elif fp.suffix.lower() == ".docx":
                loader = Docx2txtLoader(str(fp))

            docs = loader.load()
            new_docs.extend(docs)
            hashes_to_save.append(fh)  # deferred — only saved after add_documents succeeds

        except Exception as e:
            print(f"  ✗ Error loading {fp.name}: {e}")

    if new_docs:
        splits = splitter.split_documents(new_docs)
        vs.add_documents(splits)
        # Only record hashes after the embed+store actually succeeded
        for h in hashes_to_save:
            _save_hash(h)
        print(f"✓ Ingested {len(splits)} chunks from {len(new_docs)} pages.")
    else:
        print("No new documents to ingest.")


# ── Retrieval ─────────────────────────────────────────────────────────────────
def search_personal_data(query: str, k: int = 4) -> str:
    """Similarity search — returns top-k chunks as a formatted string."""
    vs      = _vectorstore()
    results = vs.similarity_search(query, k=k)

    if not results:
        return "No relevant personal data found."

    parts = []
    for i, doc in enumerate(results):
        src = Path(doc.metadata.get("source", "unknown")).name
        parts.append(f"[{src}]\n{doc.page_content.strip()}")

    return "\n\n".join(parts)
