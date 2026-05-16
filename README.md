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
| # | Feature | How |
|---|---------|-----|
| 1 | **Streaming AI chat** | Groq (llama-3.3-70b) via web UI |
| 2 | **Screenshot + Vision** | Groq Llama-4-Scout multimodal |
| 3 | **Open apps / URLs** | `subprocess` + webbrowser |
| 4 | **RAG personal memory** | LangChain + ChromaDB + HuggingFace embeddings |
| 5 | **Live weather** | Open-Meteo (free, no key) |
| 6 | **Memory browser** | Persistent markdown conversation insights |
| 7 | **YouTube ingestion** | `youtube-transcript-api` → RAG |
| 8 | **Daily briefing** | Weather + tasks combined |
| 9 | **Task tracker** | Markdown-based task detection |
| 10 | **Clipboard reader** | `pyperclip` |
| 11 | **URL scraper** | `readability-lxml` + BeautifulSoup |
| 12 | **Browser voice input** | Web Speech API |
| 13 | **Neural TTS** | Kokoro ONNX (local) → edge-tts fallback |

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
                                                   (rag/memory)  (weather/apps)
                                                      │
                                                 tts.py ──→ Audio
```

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
