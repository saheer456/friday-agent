# FRIDAY Architecture

```mermaid
graph TB
  subgraph Frontend["Frontend (React 19 + TypeScript)"]
    UI["UI Components
    ├── ChatArea (message list)
    ├── Composer (text/voice input)
    ├── Sidebar (session list)
    └── Header (status, clear)"]
    Hooks["Custom Hooks
    ├── useChat (streaming, sessions, CRUD)
    ├── useVoice (STT, TTS queue, playback)
    ├── useSystem (health polling)
    └── useFileUpload (file ingestion)"]
    Lib["Library
    ├── api.ts (authFetch SSE client)
    ├── supabase.ts (auth)
    └── localMemory.ts (limited-mode store)"]
  end

  subgraph Server["FastAPI Web Server (web/server.py)"]
    Auth["Auth Layer
    ├── Supabase JWT
    ├── API key (x-api-key)
    └── Bearer token"]
    RateLimit["Rate Limiting
    └── slowapi 20/min"]
    CORS["CORS
    └── explicit origin allowlist"]
    Endpoints["REST Endpoints
    ├── POST /api/chat/stream (SSE)
    ├── POST /api/speak (TTS pipeline)
    ├── POST /api/tts (direct TTS)
    ├── POST /api/upload (file ingest)
    ├── GET/POST/PUT/DELETE /api/sessions
    ├── GET /api/memories
    └── GET /api/system"]
  end

  subgraph Brain["Brain (backend/brain.py)"]
    ChatTurn["_iter_chat_turn()
    ├── _history_lock (session history)
    ├── context retrieval (RAG + memory)
    ├── provider streaming loop
    └── tool execution loop (max 4 rounds)"]
    ToolBridge["tool_bridge.py
    ├── JSON arg validation
    └── dispatch to SkillManager"]
    SessionHist["conversation_histories
    ├── per-session dict
    └── SQLite persistence"]
  end

  subgraph Providers["LLM Providers (backend/providers/)"]
    Manager["ProviderManager
    ├── fallback chain
    ├── cumulative error logging
    └── deploy-aware Ollama skip"]
    Groq["GroqProvider
    ├── llama-3.3-70b / llama-4-scout
    └── SSE streaming"]
    OpenRouter["OpenRouterProvider"]
    Cerebras["CerebrasProvider"]
    Ollama["OllamaProvider (local-only)"]
  end

  subgraph Skills["Skills Framework (backend/skills/)"]
    SkillManager["SkillManager
    ├── dispatch_async()
    ├── permission validation
    └── tool schema generation"]
    Skills["Registered Skills
    ├── weather_skill (Open-Meteo)
    ├── web_search_skill (DuckDuckGo)
    ├── web_scrape_skill (httpx + BS4)
    ├── code_skill (subprocess Python)
    ├── terminal_skill (shell exec)
    ├── screenshot_skill (PIL + Groq vision)
    ├── clipboard_skill (pyperclip)
    ├── app_launcher_skill (subprocess)
    ├── youtube_skill (transcript API)
    ├── gcalendar / gmail / gsheets / gdocs
    └── google_auth (OAuth)"]
  end

  subgraph Memory["Memory System (backend/memory/)"]
    ShortTerm["Short-term
    └── _context_buffer deque (last 20)"]
    LongTerm["Long-term
    ├── SQLite (memory_store.db)
    └── Supabase (optional)"]
    Semantic["Semantic
    ├── ChromaDB vector store
    └── FastEmbed embeddings"]
    ChatHistory["Chat History
    └── SQLite (chat_history table)"]
    ToolMemory["Tool Memory
    └── execution history"]
    MemoryManager["MemoryManager
    ├── retrieve_context()
    ├── save_memory()
    └── importance ranking"]
  end

  subgraph RAG["RAG Pipeline (backend/rag.py)"]
    Ingestion["Document Ingestion
    ├── PDF, DOCX, TXT, MD, CSV
    ├── LangChain loaders
    └── ChromaDB upsert"]
    Search["Vector Search
    ├── similarity_search
    └── top-k chunk retrieval"]
  end

  subgraph TTS["Text-to-Speech (backend/tts.py)"]
    CleanSpeech["clean_for_speech()
    ├── strip markdown / code / emoji
    ├── decode HTML entities
    └── remove emoticons / arrows"]
    Kokoro["Kokoro ONNX (local)
    └── kokoro_onnx + soundfile"]
    EdgeTTS["edge-tts (cloud)
    └── Microsoft neural voices"]
    Synthesis["synthesize() / synthesize_with_options()
    ├── auto (kokoro → edge fallback)
    ├── kokoro-only
    └── edge-only"]
  end

  subgraph Security["Security (backend/security/)"]
    Permissions["PermissionManager
    ├── allowlist / denylist
    ├── safe mode
    └── wired to SkillManager dispatch"]
  end

  subgraph Events["Event System (backend/events/)"]
    EventBus["EventBus
    ├── publish / subscribe
    ├── memory_saved, tool_called
    └── thinking_started, tool_finished"]
  end

  subgraph Tasks["Task Queue (backend/tasks/)"]
    TaskQueue["TaskQueue
    ├── async background jobs
    └── graceful shutdown"]
  end

  subgraph Data["Data Storage"]
    SQLite["SQLite
    ├── memory_store.db
    │   ├── chat_history
    │   ├── chat_sessions
    │   ├── session_files
    │   └── graph_nodes
    └── conversations/ (MD files)"]
    ChromaDB["ChromaDB
    ├── vectorstore/
    └── ingested document chunks"]
    Env["Environment
    ├── .env (gitignored)
    ├── GROQ_API_KEY
    ├── SUPABASE_URL/KEY
    └── FRIDAY_* config"]
  end

  %% ── Data Flow ──
  UI -->|authFetch SSE| Endpoints
  Hooks --> UI
  Lib --> Hooks

  Endpoints --> Auth
  Endpoints --> RateLimit
  Endpoints -->|POST /api/chat/stream| ChatTurn
  Endpoints -->|POST /api/speak| CleanSpeech
  CleanSpeech --> Synthesis
  Synthesis --> Kokoro
  Synthesis --> EdgeTTS
  Endpoints -->|POST /api/upload| Ingestion

  ChatTurn -->|async gen| Manager
  ChatTurn -->|_get_context| Search
  ChatTurn -->|_get_context| MemoryManager
  ChatTurn --> SessionHist

  Manager --> Groq
  Manager --> OpenRouter
  Manager --> Cerebras
  Manager --> Ollama

  ChatTurn --> ToolBridge
  ToolBridge -->|permission check| SkillManager
  SkillManager --> Skills

  MemoryManager --> ShortTerm
  MemoryManager --> LongTerm
  MemoryManager --> Semantic
  MemoryManager --> ChatHistory
  MemoryManager --> ToolMemory

  Search --> ChromaDB
  Ingestion --> ChromaDB

  SessionHist --> ChatHistory
  EventBus --> ChatTurn
  TaskQueue --> ChatTurn

  %% ── Style ──
  classDef frontend fill:#1a73e8,color:#fff
  classDef server fill:#34a853,color:#fff
  classDef brain fill:#ea4335,color:#fff
  classDef providers fill:#fbbc04,color:#000
  classDef skills fill:#ff6d01,color:#fff
  classDef memory fill:#46bdc6,color:#fff
  classDef rag fill:#ab47bc,color:#fff
  classDef tts fill:#8e24aa,color:#fff
  classDef security fill:#546e7a,color:#fff
  classDef events fill:#78909c,color:#fff
  classDef tasks fill:#90a4ae,color:#fff
  classDef data fill:#2e7d32,color:#fff

  class UI,Hooks,Lib frontend
  class Auth,RateLimit,CORS,Endpoints server
  class ChatTurn,ToolBridge,SessionHist brain
  class Manager,Groq,OpenRouter,Cerebras,Ollama providers
  class SkillManager,Skills skills
  class ShortTerm,LongTerm,Semantic,ChatHistory,ToolMemory,MemoryManager memory
  class Ingestion,Search rag
  class CleanSpeech,Kokoro,EdgeTTS,Synthesis tts
  class Permissions security
  class EventBus events
  class TaskQueue tasks
  class SQLite,ChromaDB,Env data
```

## Data Flow Summary

```
User Message
  → Frontend (useChat.ts)
  → POST /api/chat/stream (SSE)
  → brain._iter_chat_turn()
      → load session history (SQLite)
      → retrieve context (RAG + Memory)
      → ProviderManager.stream()
          → LLM provider (Groq/OpenRouter/Cerebras/Ollama)
      → Tool loop (max 4 rounds)
          → tool_bridge → SkillManager.dispatch_async()
              → PermissionManager.validate()
              → Skill execution
          → result → LLM context
      → yield tokens via SSE
  → Frontend receives tokens
      → update message list
      → sentence boundary → queueTTS()
          → POST /api/speak
              → clean_for_speech()
              → Llama cleanup (optional)
              → synthesize() (Kokoro/edge-tts)
              → return WAV/MP3
          → play audio via AudioContext
```
