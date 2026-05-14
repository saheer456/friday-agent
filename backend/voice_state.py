"""
Thread-safe pipeline state for voice STT/TTS + LLM stages.
Used by voice_in, tts, and cli to drive the live dashboard.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional


class PipelineStage(Enum):
    IDLE = auto()
    CALIBRATING = auto()
    LISTENING = auto()
    SPEECH_ONSET = auto()
    STT_LIVE = auto()
    STT_FINAL = auto()
    LLM_STREAMING = auto()
    TTS_SYNTHESIZING = auto()
    TTS_PLAYING = auto()


@dataclass
class VoicePipelineSnapshot:
    stage: PipelineStage = PipelineStage.IDLE
    live_stt: str = ""
    last_final_stt: str = ""
    input_level: float = 0.0
    tts_sentence: str = ""
    llm_token_buf: str = ""
    whisper_model: str = ""
    tts_backend: str = ""
    last_error: str = ""
    partial_count: int = 0
    utterance_count: int = 0
    last_stt_ms: float = 0.0
    updated_ts: float = field(default_factory=time.monotonic)


class VoicePipelineModel:
    """
    Observable state for the voice stack. Safe to update from background
    threads (mic / partial STT) and asyncio tasks (LLM / TTS).
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._snap = VoicePipelineSnapshot()
        self._on_change: Optional[Callable[[], None]] = None

    def set_on_change(self, cb: Optional[Callable[[], None]]):
        self._on_change = cb

    def _notify(self):
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    def snapshot(self) -> VoicePipelineSnapshot:
        with self._lock:
            return VoicePipelineSnapshot(
                stage=self._snap.stage,
                live_stt=self._snap.live_stt,
                last_final_stt=self._snap.last_final_stt,
                input_level=self._snap.input_level,
                tts_sentence=self._snap.tts_sentence,
                llm_token_buf=self._snap.llm_token_buf,
                whisper_model=self._snap.whisper_model,
                tts_backend=self._snap.tts_backend,
                last_error=self._snap.last_error,
                partial_count=self._snap.partial_count,
                utterance_count=self._snap.utterance_count,
                last_stt_ms=self._snap.last_stt_ms,
                updated_ts=time.monotonic(),
            )

    def set_stage(self, stage: PipelineStage):
        with self._lock:
            self._snap.stage = stage
            self._snap.updated_ts = time.monotonic()
        self._notify()

    def set_input_level(self, level: float):
        with self._lock:
            self._snap.input_level = max(0.0, min(1.0, level))
            self._snap.updated_ts = time.monotonic()

    def set_live_stt(self, text: str):
        with self._lock:
            self._snap.live_stt = text[:2000]
            self._snap.updated_ts = time.monotonic()
        self._notify()

    def clear_live_stt(self):
        self.set_live_stt("")

    def bump_partial(self):
        with self._lock:
            self._snap.partial_count += 1
            self._snap.updated_ts = time.monotonic()
        self._notify()

    def set_final_stt(self, text: str, ms: float):
        with self._lock:
            self._snap.last_final_stt = text[:2000]
            self._snap.last_stt_ms = ms
            self._snap.utterance_count += 1
            self._snap.live_stt = ""
            self._snap.updated_ts = time.monotonic()
        self._notify()

    def set_tts_sentence(self, text: str):
        with self._lock:
            self._snap.tts_sentence = text[:500]
            self._snap.updated_ts = time.monotonic()
        self._notify()

    def clear_tts_sentence(self):
        self.set_tts_sentence("")

    def append_llm_token(self, chunk: str):
        with self._lock:
            self._snap.llm_token_buf += chunk
            if len(self._snap.llm_token_buf) > 800:
                self._snap.llm_token_buf = self._snap.llm_token_buf[-800:]
            self._snap.updated_ts = time.monotonic()
        self._notify()

    def clear_llm_buf(self):
        with self._lock:
            self._snap.llm_token_buf = ""
            self._snap.updated_ts = time.monotonic()
        self._notify()

    def set_whisper_model(self, name: str):
        with self._lock:
            self._snap.whisper_model = name
        self._notify()

    def set_tts_backend(self, name: str):
        with self._lock:
            self._snap.tts_backend = name
        self._notify()

    def set_error(self, msg: str):
        with self._lock:
            self._snap.last_error = (msg or "")[:500]
            self._snap.updated_ts = time.monotonic()
        self._notify()

    def clear_error(self):
        with self._lock:
            self._snap.last_error = ""
        self._notify()
