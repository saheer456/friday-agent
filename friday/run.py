"""
run.py — FRIDAY launcher (Groq + HuggingFace embeddings, no Ollama needed)
"""
import os
import sys
import io
import time
import subprocess
import webbrowser
import threading
from dotenv import load_dotenv

load_dotenv()

# Fix Unicode output on Windows terminals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BANNER = (
    "\n"
    "  _______ ____  _____ ____    ___    __  __\n"
    " |  ___  |  _ \\|_   _|  _ \\  / _ \\  \\ \\/ /\n"
    " | |_  | | |_) | | | | | | |/ /_\\ \\  \\  /\n"
    " |  _| | |    /  | | | | | ||  _  |  /  \\\\\n"
    " | |   | | |\\ \\ _| |_| |_/ /| | | | / /\\ \\\\\n"
    " |_|   |_|_| \\_|_____|____/ |_| |_|/_/  \\_\\\\\n"
    "\n"
    "  SYSTEMS ONLINE  |  GROQ BACKEND  |  KOKORO TTS  |  WAITING, BOSS.\n"
)

def check_groq():
    key = os.getenv("GROQ_API_KEY", "")
    if not key or key == "your_groq_api_key_here":
        print("ERROR: GROQ_API_KEY not set in .env")
        sys.exit(1)
    print(f"✓ Groq API key found  (model: {os.getenv('GROQ_MODEL','llama-3.3-70b-versatile')})")

def main():
    print(BANNER)
    check_groq()

    print("Starting FRIDAY backend…\n")

    # Open browser after short delay
    def open_browser():
        time.sleep(2.5)
        webbrowser.open("http://localhost:8000")
    threading.Thread(target=open_browser, daemon=True).start()

    # Launch uvicorn
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        subprocess.run([
            sys.executable, "-m", "uvicorn",
            "backend.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload"
        ])
    except KeyboardInterrupt:
        print("\n\nFRIDAY signing off. Goodbye, Boss.")

if __name__ == "__main__":
    main()
