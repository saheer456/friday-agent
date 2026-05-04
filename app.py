import os
import time
import ollama
import chromadb
from chromadb.config import Settings

# --- Setup DB (persistent) ---
client = chromadb.Client(
    settings=Settings(persist_directory="./db")
)
collection = client.get_or_create_collection("docs")

# --- Simple cache for embeddings ---
cache = {}

def embed(text):
    if text in cache:
        return cache[text]
    
    emb = ollama.embeddings(
        model="nomic-embed-text",
        prompt=text
    )["embedding"]
    
    cache[text] = emb
    return emb

# --- Load documents ---
def load_docs(folder):
    docs = []
    for file in os.listdir(folder):
        path = os.path.join(folder, file)
        if file.endswith(".txt"):
            with open(path, "r", encoding="utf-8") as f:
                docs.append(f.read())
    return docs

# --- Chunking ---
def chunk(text, size=250, overlap=50):
    chunks = []
    for i in range(0, len(text), size - overlap):
        chunks.append(text[i:i+size])
    return chunks

# --- Store embeddings ---
def store(chunks):
    for i, c in enumerate(chunks):
        collection.add(
            ids=[str(i)],
            embeddings=[embed(c)],
            documents=[c]
        )

# --- Retrieve ---
def search(query):
    results = collection.query(
        query_embeddings=[embed(query)],
        n_results=3   # reduced
    )
    
    docs = results["documents"][0]
    return docs[:2]   # limit context

# --- Generate Answer ---
def answer(query, context):
    context_text = "\n".join(context)

    prompt = f"""
You are a strict QA system.

Rules:
- Use ONLY the context
- If not found, say: I don't know
- No guessing
- Keep answer short

Context:
{context_text}

Question: {query}

Answer:
"""

    res = ollama.generate(
        model="phi3:mini",
        prompt=prompt
    )

    return res["response"]

# --- MAIN ---
if __name__ == "__main__":
    
    docs = load_docs("data")

    all_chunks = []
    for d in docs:
        all_chunks.extend(chunk(d))

    # store only once
    if collection.count() == 0:
        store(all_chunks)

    print("✅ RAG Ready. Ask questions...\n")

    while True:
        q = input("Ask: ")

        start = time.time()

        ctx = search(q)
        ans = answer(q, ctx)

        end = time.time()

        print("\nAnswer:", ans)
        print(f"⏱ Time taken: {round(end - start, 2)} sec\n")