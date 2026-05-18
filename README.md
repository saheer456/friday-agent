# FRIDAY — AI Voice Assistant

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Groq-LLM_API-F55036?logo=groq&logoColor=white" />
  <img src="https://img.shields.io/badge/ChromaDB-RAG-6B4EFF" />
  <img src="https://img.shields.io/badge/License-MIT-green" />
</div>

---

**FRIDAY** is a fully local, voice-first AI assistant powered by Groq's ultra-fast LLM API. It listens, thinks, speaks back, remembers context, searches the web, reads your screen, manages files, and runs via a web UI.

## ✨ Features

| # | Feature | How |
|---|---------|-----|
| 1 | **Streaming AI chat** | Groq / OpenRouter / Cerebras via SSE |
| 2 | **Screenshot + Vision** | Groq Llama-4-Scout multimodal |
| 3 | **Open apps / URLs** | `subprocess` + webbrowser |
| 4 | **RAG personal memory** | LangChain + ChromaDB + HuggingFace embeddings |
| 5 | **Live weather** | Open-Meteo (free, no key) |
| 6 | **Memory management UI** | Browse, search, add, and delete memories from the web UI |
| 7 | **YouTube ingestion** | `youtube-transcript-api` → RAG |
| 8 | **Daily briefing** | Weather + tasks combined |
| 9 | **Task tracker** | Markdown-based task detection |
| 10 | **Clipboard reader** | `pyperclip` |
| 11 | **URL scraper** | `readability-lxml` + BeautifulSoup |
| 12 | **Browser voice input** | Web Speech API (interim results, server-side Whisper fallback) |
| 13 | **Neural TTS** | Kokoro ONNX (local) → edge-tts fallback |
| 14 | **Auto memory ranking** | Heuristic importance scoring (no API call per exchange) |

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- A free [Groq API key](https://console.groq.com/)
- A microphone (for voice input)

### 1. Clone & install

```bash
git clone https://github.com/saheer456/friday-agent.git
cd friday-agent/friday
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Open .env and add your GROQ_API_KEY
```

### 3. (Optional) Neural TTS — Kokoro

For the best voice quality, download the Kokoro ONNX model files and place them in the `friday/` directory:

```
kokoro-v1.0.onnx
voices-v1.0.bin
```

Then set `TTS_BACKEND=kokoro` in `.env`. Without Kokoro, FRIDAY uses Microsoft Edge TTS (online) fallback.

### 4. Run FRIDAY (Web UI)

```bash
# From the friday/ directory:
start_web.bat        # Windows — builds frontend + starts server
# or
start.bat            # Windows — quick start (server only, assumes frontend already built)
```

Then open **http://127.0.0.1:8080** in your browser.

### 5. (Recommended) Enable Supabase Login Before Sharing

If you're sending the project to recruiters/testers, enable Supabase JWT auth:

```bash
FRIDAY_SUPABASE_AUTH_ENABLED=1
FRIDAY_FULL_ACCESS_EMAILS=khansaheer424@gmail.com
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key

# Frontend env (Vite)
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
```

With this enabled, the frontend signs users in via Supabase Auth, then sends Supabase JWT bearer tokens to backend APIs.

Access levels:
- Emails in `FRIDAY_FULL_ACCESS_EMAILS` get the full assistant.
- Other signed-in users get basic demo chat, weather, and browser-local memory only.

## 📁 Project Structure

```
friday/
├── backend/                    # Python backend
│   ├── __init__.py
│   ├── brain.py                # Groq LLM + routing + memory + tool calling
│   ├── rag.py                  # LangChain + ChromaDB ingestion & retrieval
│   ├── tts.py                  # Kokoro / edge-tts synthesis
│   ├── search.py               # DuckDuckGo web search
│   ├── scraper.py              # URL content scraper
│   ├── tools.py                # Local capability tools (weather, apps, etc.)
│   ├── memory/                 # Long-term + short-term memory system
│   ├── skills/                 # Tool-calling skills framework
│   ├── file_intelligence.py    # File upload RAG pipeline
│   └── tool_bridge.py          # LLM tool call dispatcher
├── web/
│   ├── server.py               # FastAPI server (SSE streaming, file upload, TTS)
│   ├── static/                 # Legacy static frontend
│   └── __init__.py
├── frontend/                   # React 19 + TypeScript + Vite UI
├── data/                       # Personal documents (gitignored)
├── vectorstore/                # ChromaDB store (gitignored, auto-generated)
├── start_web.bat               # Full startup: builds frontend + starts server
├── start.bat                   # Quick start (server only)
├── requirements.txt
└── .env.example
```

## ⚙️ Environment Variables

See [`.env.example`](friday/.env.example) for all options.

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | — | **Required.** Get one at console.groq.com |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Active Groq model |
| `TTS_BACKEND` | `kokoro` | `kokoro` / `edge` |
| `FRIDAY_VOICE` | `bf_emma` | Kokoro voice ID |
| `FRIDAY_TTS_SPEED` | `1.1` | Speech rate (0.7–1.4) |
| `FRIDAY_LAT` | `28.6` | Latitude for weather lookups |
| `FRIDAY_LON` | `77.2` | Longitude for weather lookups |

## 🏗️ Architecture

```
Browser (React) ──→ FastAPI (web/server.py) ──→ LLM Engine (brain.py)
                                                      │
                                             ┌────────┼────────────┐
                                             ▼        ▼            ▼
                                         Groq LLM  ChromaDB      Tools
                                                   (memory/)    (weather/apps)
                                                      │
                                                 tts.py ──→ Audio

Memory tiers:
  Short-term (rolling buffer, 20 exchanges)
  Long-term  (SQLite / Supabase, importance-scored)
  Semantic   (ChromaDB vector embeddings, auto-categorized)
```

## 📡 API Reference

All endpoints served from `http://127.0.0.1:8080`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/system` | Voice/LLM stack info + readiness |
| `POST` | `/api/chat/stream` | SSE streaming chat (phase + token + error events) |
| `POST` | `/api/chat` | Non-streaming chat (full reply as JSON) |
| `POST` | `/api/tts` | Synthesize text → audio (MP3/WAV) |
| `POST` | `/api/speak` | Markdown → spoken prose → audio (via Groq rewrite) |
| `POST` | `/api/stt` | Upload audio → transcribed text (faster-whisper) |
| `POST` | `/api/upload` | Ingest a file (PDF, DOCX, TXT, CSV, JSON, MD) |
| `POST` | `/api/clear` | Clear conversation history |
| `GET` | `/api/memories` | List stored memories (paginated, `?limit=&offset=`) |
| `POST` | `/api/memories` | Add a memory manually (`{content, category, importance}`) |
| `DELETE` | `/api/memories/:id` | Delete a specific memory |

## 🧠 Memory System

Three-tier memory architecture:

**1. Short-term buffer** (`memory/short_term.py`)
- Rolling deque of the last 20 exchanges (4000 chars max)
- Always injected into LLM context for conversational continuity

**2. Long-term SQLite / Supabase** (`memory/long_term.py`)
- Persists important memories (importance ≥ 0.4) to disk
- Auto-detects Supabase if `SUPABASE_URL` + `SUPABASE_KEY` are set, otherwise falls back to local SQLite
- Persistent connection pooling (no open/close per operation)

**3. Semantic vector store** (`memory/semantic_memory/`)
- Embeddings via FastEmbed (`BAAI/bge-small-en-v1.5`, ONNX runtime, ~30MB)
- Stored in ChromaDB (local) or Supabase pgvector (production)
- Automatically cross-searched on every query for relevant context

**Memory ranking** (`memory/memory_ranker.py`)
- Scores importance using a multi-factor heuristic (keywords, entities, information density, numeric facts) — no API call per exchange
- 7 categories: `security_notes`, `personal_info`, `user_preference`, `project`, `task`, `learning`, `casual`
- Runs in microseconds, called after every assistant response

## 📦 Dependencies

Key packages — see [`requirements.txt`](friday/requirements.txt) for the full pinned list.

- **LLM**: `groq`, `httpx`
- **RAG**: `langchain`, `langchain-chroma`, `sentence-transformers`, `chromadb`
- **STT**: Browser Web Speech API (frontend) / `faster-whisper` (optional)
- **TTS**: `kokoro-onnx`, `edge-tts`, `pygame`, `soundfile`
- **Tools**: `duckduckgo-search`, `beautifulsoup4`, `pillow`, `pyperclip`

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*"Sometimes you gotta run before you can walk." — Tony Stark*
