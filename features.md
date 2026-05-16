# Memory & STT System — Current State

## Memory System

### Architecture
- **Short-term buffer:** Rolling deque of 20 exchanges, always injected into LLM context.
- **Long-term storage:** SQLite (local) or Supabase (production) — persistent importance-scored memories.
- **Semantic search:** ChromaDB (local) or Supabase pgvector — FastEmbed ONNX embeddings (bge-small-en-v1.5).

### Implemented
- **Direct Memory Entry:** `POST /api/memories` — add memories via API or web UI.
- **Memory Browsing & Deletion:** Memories panel in the web UI with list/refresh/delete; backed by `GET /api/memories` and `DELETE /api/memories/:id`.
- **Memory Ranking:** Multi-factor heuristic (keywords, entities, info density, numeric facts) — no LLM API call per exchange. Categories: security_notes, personal_info, user_preference, project, task, learning, casual.
- **SQLite Connection Pooling:** Persistent single connection instead of open/close per op.
- **RAG & Long-Term Memory Unification:** Both systems active; semantic search queries vector store on every exchange.

### Not Yet Implemented
- Memory editing (update existing memory content).
- Memory tagging and advanced search/filtering by tag, date, or category in the UI.
- Import/export of memory database.
- Automatic memory consolidation (periodic summarization of related entries).
- Temporal decay (reduce importance of unaccessed memories over time).

## STT (Voice-to-Text) System

### Current
- **Browser Web Speech API** (Chrome/Edge/Safari) with interim results displayed as placeholder text.
- **Server-side Whisper fallback:** `POST /api/stt` accepts audio uploads via faster-whisper.

### Fixed
- Race condition between `onresult` and `onend` (uses `useRef` instead of closure `let`).
- Stale closure on React re-render.
- No interim display → now shows live transcription while speaking.
