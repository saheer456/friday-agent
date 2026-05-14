# FRIDAY System Roadmap

## PHASE 1 — Stabilize Existing System FIRST
**Goal**: Make FRIDAY reliable. Do NOT add advanced AI memory while your core assistant is unstable.

### Tasks
1. **Fix OpenRouter 429 handling**
   - Add retry logic
   - Add cooldowns
   - Add request queue
2. **Add structured logging**
   - Create `logs/` directory
   - Use `logging` module
   - Store: API failures, OAuth failures, tool errors, memory retrieval failures
3. **Environment validation**
   - At startup: check API keys, check credential files, check vector DB exists
   - Fail early.
4. **Fix threading/async issues**
   - Standardize: asyncio everywhere if possible
   - Avoid: random threads + async mixed carelessly

**RESULT OF PHASE 1**: Stable assistant, debuggable architecture, reliable API behavior. Only then continue.

---

## PHASE 2 — Build Core Memory Layer
**Goal**: This is foundational.

### Tasks
1. **Create Memory Architecture**
   - Create `friday/memory/`
   - Structure: `short_term.py`, `long_term.py`, `semantic_memory.py`, `memory_manager.py`, `memory_ranker.py`, `memory_store.db`
2. **Implement Short-Term Memory**
   - Use `collections.deque` (maxlen=20) for conversation continuity
   - Stores: recent prompts, recent responses, temporary context
3. **Implement Long-Term Memory**
   - Use SQLite (easy, stable, local, lightweight)
   - Table Structure: `id`, `content`, `category`, `importance`, `created_at`
   - Categories: project, user_preference, task, learning, security_notes
4. **Build Memory Manager**
   - Central controller: save, retrieve, rank, delete, summarize
5. **Add Importance Scoring**
   - High Importance: career goals, ongoing projects, API credentials paths
   - Low Importance: “hello”, “thanks”
6. **Inject Memory Into Prompts**
   - Flow: User Prompt -> Retrieve Relevant Memories -> Build Context -> Send To LLM

**RESULT OF PHASE 2**: FRIDAY now remembers projects, recalls past context, maintains continuity.

---

## PHASE 3 — Semantic Memory (Real Intelligence)
**Goal**: Add vector search.

### Tasks
1. **Install Embedding Stack**
   - Use `sentence-transformers`, `chromadb`
2. **Embedding Model**
   - Recommended: `all-MiniLM-L6-v2` (fast, lightweight, enough quality)
3. **Create Semantic Store**
   - Structure: `embedder.py`, `vector_store.py`, `retrieval.py`
4. **Embed Memories**
   - Store vector, metadata, timestamps
5. **Semantic Retrieval**
   - Retrieve relevant knowledge even without exact keywords.

**RESULT OF PHASE 3**: FRIDAY now understands concepts, retrieves relevant knowledge, behaves intelligently.

---

## PHASE 4 — File Intelligence System
**Goal**: Build modern RAG properly.

### Tasks
1. **Create File Intelligence Module**
   - Structure: `parsers/`, `chunking/`, `embeddings/`, `retrieval/`, `analysis/`
2. **File Parsers**
   - Implement support for PDF (`pypdf`), DOCX (`python-docx`), CSV (`pandas`), TXT, JSON
3. **Chunking Engine**
   - Chunk size: 500–800 tokens, Overlap: 100 tokens
4. **Embedding Pipeline**
   - Extract text, clean text, embed, store in vector DB
5. **Metadata System**
   - Store: file, page, topic, chunk
6. **Retrieval Pipeline**
   - Question -> Embed Question -> Find Similar Chunks -> Inject Into Prompt -> LLM Answer

**RESULT OF PHASE 4**: FRIDAY searches files intelligently, answers from documents.

---

## PHASE 5 — Advanced File Intelligence

### Add These Features
1. **Code Analysis**: Explain functions, detect vulnerabilities, summarize architecture
2. **Log Analysis**: Analyze Apache logs, auth logs, SIEM exports
3. **Auto Categorization**: Classify security, python, networking, cloud
4. **Study Assistant**: Generate flashcards, quizzes, summaries
5. **OCR Support**: Read screenshots, scanned PDFs (`pytesseract`)

---

## PHASE 6 — Multi-Agent Orchestration
**Goal**: Only AFTER previous phases are stable. Build Specialized Agents.

### Tasks
- **Agents**: Memory Agent, RAG Agent, Tool Agent, Planner Agent, Security Agent
- **Workflow**: Planner decides -> Agents execute -> Combine results -> LLM final answer

**RESULT OF PHASE 6**: Behaviors like an actual AI system.

### Recommended Tech Stack
- Memory DB: SQLite
- Vector DB: ChromaDB
- Embeddings: sentence-transformers
- Parsing: pypdf/python-docx
- Async: asyncio
- Logging: logging
- Config: pydantic
- API calls: httpx

### Biggest Trap To Avoid
- Do NOT: (Text cut off - likely "Do NOT build advanced features before the core loop is perfectly stable")
