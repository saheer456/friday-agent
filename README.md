# FRIDAY — AI Voice Assistant

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Groq-LLM_API-F55036?logo=groq&logoColor=white" />
  <img src="https://img.shields.io/badge/ChromaDB-RAG-6B4EFF" />
  <img src="https://img.shields.io/badge/License-MIT-green" />
</div>

---

**FRIDAY** is a fully local, voice-first AI assistant powered by Groq's ultra-fast LLM API. Think J.A.R.V.I.S. — it listens, thinks, speaks back, remembers context, searches the web, reads your screen, manages files, and runs on your machine.

## ✨ Features

| # | Feature | How |
|---|---------|-----|
| 1 | **Streaming AI chat** | Groq (llama-3.3-70b) via WebSocket |
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
| 12 | **Always-on VAD** | WebRTC VAD + faster-whisper (Whisper Small) |
| 13 | **Neural TTS** | Kokoro ONNX (local) → edge-tts → browser fallback |
| 14 | **Model switcher** | Live Groq model selection from UI |
| 15 | **File upload ingestion** | Drag-and-drop → instant RAG |

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

Then set `TTS_BACKEND=kokoro` in `.env`. Without Kokoro, FRIDAY uses Microsoft Edge TTS (online) or browser speech.

### 4. Run FRIDAY

```bash
# From the friday/ directory:
python run.py

# Or directly:
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000** in your browser.

## 📁 Project Structure

```
friday-agent/
├── friday/                     # Main application package
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI app & all API endpoints
│   │   ├── brain.py            # Groq LLM + routing + memory
│   │   ├── rag.py              # LangChain + ChromaDB ingestion & retrieval
│   │   ├── voice_in.py         # Always-on VAD + faster-whisper STT
│   │   ├── voice_out.py        # Audio playback helper
│   │   ├── tts.py              # Kokoro / edge-tts synthesis
│   │   ├── search.py           # DuckDuckGo web search
│   │   ├── scraper.py          # URL content scraper
│   │   └── system.py           # CPU/RAM stats
│   ├── frontend/
│   │   ├── index.html          # Futuristic HUD UI
│   │   ├── style.css
│   │   └── app.js
│   ├── data/                   # Your personal documents (gitignored)
│   │   └── profile.txt         # Boss profile — always injected in context
│   ├── vectorstore/            # ChromaDB store (gitignored, auto-generated)
│   ├── requirements.txt
│   ├── run.py                  # Launch script
│   ├── cli.py                  # CLI mode
│   ├── start.bat               # Windows one-click launch
│   └── .env.example
├── .gitignore
├── LICENSE
└── README.md
```

## ⚙️ Environment Variables

See [`.env.example`](friday/.env.example) for all options.

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | — | **Required.** Get one at console.groq.com |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Active Groq model |
| `TTS_BACKEND` | `browser` | `browser` / `kokoro` / `edge` |
| `FRIDAY_VOICE` | `bf_emma` | Kokoro voice ID |
| `FRIDAY_TTS_SPEED` | `1.1` | Speech rate (0.7–1.4) |

## 🏗️ Architecture

```
Browser ─── WebSocket ──→ FastAPI (brain.py)
                               │
              ┌────────────────┼────────────────────┐
              ▼                ▼                    ▼
         Groq LLM        ChromaDB RAG         Tools / APIs
     (stream tokens)   (personal memory)  (weather/apps/web)
              │
         voice_out ──→ TTS Engine (Kokoro / edge-tts)
```

## 📦 Dependencies

Key packages — see [`requirements.txt`](friday/requirements.txt) for the full pinned list.

- **LLM**: `groq`, `httpx`
- **RAG**: `langchain`, `langchain-chroma`, `sentence-transformers`, `chromadb`
- **STT**: `faster-whisper`, `webrtcvad-wheels`, `pyaudio`
- **TTS**: `kokoro-onnx`, `edge-tts`, `pygame`, `soundfile`
- **Web**: `fastapi`, `uvicorn[standard]`
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
