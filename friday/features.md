# 🚀 FRIDAY System Features

FRIDAY (Federated Response Intelligence & Digital Assistant Yield) is a production-grade, voice-first AI assistant inspired by JARVIS/FRIDAY.

## 🎙️ High-Fidelity Voice Interface
- **Holographic Arc Reactor HUD:** Interactive CSS-only animation that pulses and rotates during AI speech.
- **Natural Prose Pipeline:** Uses an LLM-powered rewrite engine to convert raw Markdown into natural human speech patterns before synthesis.
- **Low-Latency Interruption:** Integrated `AbortController` in the frontend allows instantaneous audio cancellation when a new command is issued.
- **Multi-Backend TTS/STT:** Support for Edge-TTS, Kokoro-ONNX, and OpenAI-compatible pipelines.
- **Live Status Badges:** Real-time telemetry for Memory, TTS, and STT readiness.

## 🧠 Intelligence & Memory
- **RAG Substrate:** ChromaDB-powered vector storage for document and personal data recall.
- **Mem0 Integration:** Long-term episodic memory that tracks user preferences and history.
- **MiniLM Intent Routing:** Zero-cost local embedding model (`all-MiniLM-L6-v2`) used for near-zero latency intent detection and skill routing.
- **Multi-Provider Support:** Seamless switching between Groq (Llama 3.3/3.1) and OpenRouter (Qwen/DeepSeek).

## 🛠️ Skills Framework (Extensible)
Modular system allowing FRIDAY to autonomously interact with the local system and cloud services.

### 💻 Developer Skills (`code`)
- **Code Generation:** Clean, production-ready code in any language.
- **Sandboxed Execution:** Safely run Python code in a local subprocess and return stdout/stderr.
- **Code Review:** Autonomous analysis of complexity, bugs, and performance.
- **Auto-Debugger:** Can read tracebacks and fix its own generated code.

### 🖥️ System Skills (`terminal`)
- **Shell Access:** Run commands in PowerShell/Bash with a safety blocklist.
- **File Management:** Read/Write files and list directories within a secure workspace boundary.

### ☁️ Google Workspace Integration (Full Access)
- **Gmail:** Send emails and read inbox/unread messages.
- **Google Calendar:** Create, list, and delete real events.
- **Google Docs:** Create and read documents (auto-opens in browser).
- **Google Sheets:** Create spreadsheets and append/read row data (auto-opens in browser).

## 🧰 Integrated Utilities
- **Visual Intelligence:** Groq-powered screenshot analysis ("What's on my screen?").
- **Knowledge Ingestion:** Ingest YouTube transcripts and URLs directly into long-term memory.
- **Productivity:** Daily briefings, task management, clipboard reading, and weather integration.

## 🌐 Modern Web UI
- **Premium Dark Mode:** High-tech "Stark Industries" aesthetic.
- **SSE Token Streaming:** Real-time character-by-character response delivery.
- **Cache-Busting Deployment:** Version-controlled asset loading for instant updates.
