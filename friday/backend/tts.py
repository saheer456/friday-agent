"""
tts.py  —  Voice output for FRIDAY CLI.

Synthesis:
  1. Kokoro ONNX  (local, ~80 MB, best quality) — if installed
  2. edge-tts     (Microsoft online, high quality British female) — fallback

Playback:
  play_interruptible(audio_bytes, stop_event, is_mp3)
    Uses pygame.mixer for both WAV and MP3.
    Checks stop_event every 50 ms — aborts immediately when set.
"""

import asyncio
import io
import os
import re
import tempfile
import threading
import time

VOICE = os.getenv("FRIDAY_VOICE", "af_bella")
DEFAULT_SPEED = float(os.getenv("FRIDAY_TTS_SPEED", "1.1"))
KOKORO_MODEL_PATH = os.getenv("FRIDAY_TTS_MODEL", "kokoro-v1.0.onnx")
KOKORO_VOICES_PATH = os.getenv("FRIDAY_TTS_VOICES", "voices-v1.0.bin")

# Also check common alternate model filename
if not os.path.exists(KOKORO_MODEL_PATH) and os.path.exists("tts-1-hd"):
    KOKORO_MODEL_PATH = "tts-1-hd"

_kokoro      = None
_kokoro_disabled = False
_pygame_init = False


# ─────────────────────────────────────────────────────────────────────────────
#  Text cleaning
# ─────────────────────────────────────────────────────────────────────────────
def clean_for_speech(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "code block", text)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"https?:\S+", "", text)
    text = re.sub(r"[*_]{1,2}", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"[#>]", "", text)
    # Remove tables, repeated punctuation, split numbers
    text = re.sub(r'\|\s*-+\s*\|', '', text)  # tables
    text = re.sub(r'([!?.])\1+', r'\1', text)  # !!! → !
    text = re.sub(r'(\d{3,})', r' \1 ', text)  # numbers spaced
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
#  Pygame init (lazy, once)
# ─────────────────────────────────────────────────────────────────────────────
def _ensure_pygame():
    global _pygame_init
    if not _pygame_init:
        import pygame
        pygame.mixer.pre_init(frequency=24000, size=-16, channels=1, buffer=512)
        pygame.mixer.init()
        _pygame_init = True


# ─────────────────────────────────────────────────────────────────────────────
#  Playback — works with both WAV and MP3
# ─────────────────────────────────────────────────────────────────────────────
def play_interruptible(audio_bytes: bytes, stop_event: threading.Event,
                       suffix: str = ".mp3"):
    """
    Play audio_bytes (MP3 or WAV) via pygame.mixer.
    Polls stop_event every 50 ms and stops immediately if set.
    Run this in a thread executor — it blocks until done or interrupted.
    """
    if not audio_bytes or stop_event.is_set():
        return

    tmp_path = None
    try:
        import pygame
        _ensure_pygame()

        # Write to temp file (pygame needs a file path for loading)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            if stop_event.is_set():
                pygame.mixer.music.stop()
                break
            time.sleep(0.05)

    except Exception as e:
        print(f"[TTS] Playback error: {e}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ─────────────────────────────────────────────────────────────────────────────
#  Synthesis — Kokoro primary, edge-tts fallback
# ─────────────────────────────────────────────────────────────────────────────
def _clamp_speed(speed: float | None) -> float:
    if speed is None:
        return DEFAULT_SPEED
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        return DEFAULT_SPEED
    return max(0.7, min(1.4, speed))


def _edge_rate(speed: float) -> str:
    pct = round((speed - 1.0) * 100)
    pct = max(-30, min(40, pct))
    return f"{pct:+d}%"


def _get_kokoro():
    global _kokoro, _kokoro_disabled
    if _kokoro_disabled:
        raise RuntimeError("Kokoro is unavailable")
    if _kokoro is None:
        if not os.path.exists(KOKORO_MODEL_PATH) or not os.path.exists(KOKORO_VOICES_PATH):
            _kokoro_disabled = True
            raise FileNotFoundError(
                f"Kokoro model files not found: {KOKORO_MODEL_PATH}, {KOKORO_VOICES_PATH}"
            )
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(KOKORO_MODEL_PATH, KOKORO_VOICES_PATH)
    return _kokoro


def _synth_kokoro_sync(text: str, speed: float) -> tuple[bytes, str]:
    """Returns (wav_bytes, '.wav')"""
    import soundfile as sf
    kokoro = _get_kokoro()
    samples, sr = kokoro.create(text, voice=VOICE, speed=speed, lang="en-us")
    buf = io.BytesIO()
    sf.write(buf, samples, sr, format="WAV")
    return buf.getvalue(), ".wav"


async def _synth_edge(text: str, speed: float) -> tuple[bytes, str]:
    """Returns (mp3_bytes, '.mp3')"""
    try:
        import edge_tts
        comm  = edge_tts.Communicate(text, "en-GB-SoniaNeural", rate=_edge_rate(speed))
        audio = b""
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return audio, ".mp3"
    except Exception as e:
        print(f"[TTS] edge-tts error: {e}")
        return b"", ".mp3"


async def synthesize(text: str, speed: float | None = None) -> tuple[bytes, str]:
    """
    Synthesise text → (audio_bytes, file_suffix).
    Returns suffix so caller knows format for playback.
    """
    cleaned = clean_for_speech(text)
    if not cleaned:
        return b"", ".mp3"

    speed = _clamp_speed(speed)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _synth_kokoro_sync, cleaned, speed)
        return result
    except Exception as e:
        print(f"[TTS] Kokoro failed ({e}) — using edge-tts")
        return await _synth_edge(cleaned, speed)


