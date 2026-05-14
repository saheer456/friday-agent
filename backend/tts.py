"""
tts.py — Voice output for FRIDAY CLI.

Synthesis backends (FRIDAY_TTS_BACKEND):
  auto   — try Kokoro ONNX if model files exist, else edge-tts (default)
  kokoro — local Kokoro only (fails if models missing)
  edge   — Microsoft edge-tts only

Returns (audio_bytes, suffix, echo_pcm16k) where echo_pcm16k is the first
~30 ms of mono s16le audio at 16_000 Hz for microphone echo comparison.
Playback picks pygame mixer sample rate from WAV; MP3 uses 24_000 Hz default.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np

VOICE = os.getenv("FRIDAY_VOICE", "af_heart")
DEFAULT_SPEED = float(os.getenv("FRIDAY_TTS_SPEED", "1.1"))
KOKORO_MODEL_PATH = os.getenv("FRIDAY_TTS_MODEL", "kokoro-v1.0.onnx")
KOKORO_VOICES_PATH = os.getenv("FRIDAY_TTS_VOICES", "voices-v1.0.bin")
TTS_BACKEND = os.getenv("FRIDAY_TTS_BACKEND", "auto").strip().lower()

if not os.path.exists(KOKORO_MODEL_PATH) and os.path.exists("tts-1-hd"):
    KOKORO_MODEL_PATH = "tts-1-hd"

_kokoro = None
_kokoro_disabled = False
_pygame_init = False
_mixer_output_sr = 24_000
_last_audio_bytes: bytes = b""


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", "code block", text)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"https?:\S+", "", text)
    text = re.sub(r"[*_]{1,2}", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"[#>]", "", text)
    text = re.sub(r"\|\s*-+\s*\|", "", text)
    text = re.sub(r"([!?.])\1+", r"\1", text)
    text = re.sub(r"(\d{3,})", r" \1 ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _pcm16k_prefix(samples: np.ndarray, source_sr: int, max_ms: float = 40.0) -> bytes:
    """First ~max_ms of audio as int16 mono at 16 kHz (for echo ref)."""
    if samples.size == 0 or source_sr <= 0:
        return b""
    mono = samples.astype(np.float32, copy=False)
    if mono.ndim > 1:
        mono = mono.mean(axis=1)
    target_n = int(16_000 * (max_ms / 1000.0))
    if source_sr != 16_000:
        t_src = np.linspace(0.0, len(mono) / source_sr, num=len(mono), endpoint=False)
        t_dst = np.linspace(0.0, target_n / 16_000, num=target_n, endpoint=False)
        mono = np.interp(t_dst, t_src, mono).astype(np.float32)
    else:
        mono = mono[:target_n]
    mono = np.clip(mono, -1.0, 1.0)
    return (mono * 32767.0).astype(np.int16).tobytes()


def _ensure_pygame(sample_rate: int = 24_000):
    global _pygame_init, _mixer_output_sr
    import pygame

    if _pygame_init and _mixer_output_sr == sample_rate:
        return
    if _pygame_init:
        pygame.mixer.quit()
        _pygame_init = False
    pygame.mixer.pre_init(frequency=sample_rate, size=-16, channels=1, buffer=512)
    pygame.mixer.init()
    _pygame_init = True
    _mixer_output_sr = sample_rate


def play_interruptible(
    audio_bytes: bytes,
    stop_event: threading.Event,
    suffix: str = ".mp3",
    echo_pcm16k: bytes | None = None,
):
    """
    Play audio via pygame.mixer. Polls stop_event every 50 ms.
    echo_pcm16k: optional; if provided, stored for mic echo detection (int16 16kHz).
    """
    if not audio_bytes or stop_event.is_set():
        return
    global _last_audio_bytes
    _last_audio_bytes = echo_pcm16k[:960] if echo_pcm16k else b""

    tmp_path = None
    try:
        import pygame

        play_sr = 24_000
        if suffix.lower() == ".wav":
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                play_sr = wf.getframerate()
                ch = wf.getnchannels()
                if ch != 1:
                    play_sr = play_sr  # still try mono rate
        _ensure_pygame(play_sr)

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


def _synth_kokoro_sync(text: str, speed: float, voice: str = VOICE) -> tuple[bytes, str, bytes]:
    import soundfile as sf

    kokoro = _get_kokoro()
    samples, sr = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
    echo = _pcm16k_prefix(samples, sr)
    buf = io.BytesIO()
    sf.write(buf, samples, sr, format="WAV")
    return buf.getvalue(), ".wav", echo


def _decode_mp3_echo_pcm16k(mp3: bytes) -> bytes:
    if not mp3 or not shutil.which("ffmpeg"):
        return b""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3)
        mp3_path = f.name
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                mp3_path,
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-acodec",
                "pcm_s16le",
                "pipe:1",
            ],
            capture_output=True,
            timeout=60,
        )
        raw = proc.stdout or b""
        return raw[:960]
    except (OSError, subprocess.SubprocessError):
        return b""
    finally:
        try:
            os.unlink(mp3_path)
        except OSError:
            pass


async def _synth_edge(text: str, speed: float) -> tuple[bytes, str, bytes]:
    try:
        import edge_tts

        comm = edge_tts.Communicate(text, "en-GB-RyanNeural", rate=_edge_rate(speed))
        audio = b""
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        echo = _decode_mp3_echo_pcm16k(audio)
        return audio, ".mp3", echo
    except Exception as e:
        print(f"[TTS] edge-tts error: {e}")
        return b"", ".mp3", b""


async def synthesize(text: str, speed: float | None = None) -> tuple[bytes, str, bytes]:
    cleaned = clean_for_speech(text)
    if not cleaned:
        return b"", ".mp3", b""

    speed = _clamp_speed(speed)
    loop = asyncio.get_running_loop()
    backend = TTS_BACKEND

    async def _kokoro() -> tuple[bytes, str, bytes]:
        return await loop.run_in_executor(None, _synth_kokoro_sync, cleaned, speed)

    if backend == "edge":
        return await _synth_edge(cleaned, speed)
    if backend == "kokoro":
        try:
            return await _kokoro()
        except Exception as e:
            print(f"[TTS] Kokoro failed ({e})")
            return await _synth_edge(cleaned, speed)

    # auto
    try:
        return await _kokoro()
    except Exception as e:
        print(f"[TTS] Kokoro unavailable ({e}) — edge-tts")
        return await _synth_edge(cleaned, speed)


async def synthesize_with_options(
    text: str,
    voice: str | None = None,
    emotion: str = "neutral",
    speed: float | None = None,
) -> tuple[bytes, str, bytes]:
    emotion_params = {
        "neutral": {"speed": 1.0},
        "happy": {"speed": 1.15},
        "sad": {"speed": 0.85},
        "professional": {"speed": 1.0},
        "excited": {"speed": 1.25},
    }
    params = emotion_params.get(emotion, emotion_params["neutral"])
    base_speed = _clamp_speed(speed)
    final_speed = base_speed * params["speed"]
    target_voice = voice if voice else VOICE

    cleaned = clean_for_speech(text)
    if not cleaned:
        return b"", ".mp3", b""

    loop = asyncio.get_running_loop()
    backend = TTS_BACKEND

    async def _kokoro_em() -> tuple[bytes, str, bytes]:
        return await loop.run_in_executor(
            None, _synth_kokoro_sync, cleaned, final_speed, target_voice
        )

    if backend == "edge":
        return await _synth_edge(cleaned, final_speed)
    if backend == "kokoro":
        try:
            return await _kokoro_em()
        except Exception as e:
            print(f"[TTS] Kokoro failed ({e}) — edge-tts")
            return await _synth_edge(cleaned, final_speed)

    try:
        return await _kokoro_em()
    except Exception as e:
        print(f"[TTS] Kokoro unavailable ({e}) — edge-tts")
        return await _synth_edge(cleaned, final_speed)
