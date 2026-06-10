"""Application state service - provides multi-worker safe state management."""
import asyncio
import threading
import logging
from typing import Optional

logger = logging.getLogger("AppState")


class AppState:
    """Thread-safe application state with Redis-ready interface.
    In a multi-worker deployment, replace local storage with Redis
    without changing the public API.
    """

    def __init__(self):
        self._memory_ready: bool = False
        self._stt_ready: bool = True
        self._whisper_model: object = None
        self._memory_ready_lock = threading.Lock()
        self._whisper_lock = asyncio.Lock()
        self._tts_ready = threading.Event()

    # ── TTS ─────────────────────────────────────────────────────

    def set_tts_ready(self) -> None:
        self._tts_ready.set()

    def is_tts_ready(self) -> bool:
        return self._tts_ready.is_set()

    @property
    def tts_ready_event(self) -> threading.Event:
        return self._tts_ready

    # ── Memory ──────────────────────────────────────────────────

    @property
    def memory_ready(self) -> bool:
        with self._memory_ready_lock:
            return self._memory_ready

    @memory_ready.setter
    def memory_ready(self, value: bool) -> None:
        with self._memory_ready_lock:
            self._memory_ready = value

    # ── STT ─────────────────────────────────────────────────────

    @property
    def stt_ready(self) -> bool:
        return self._stt_ready

    @stt_ready.setter
    def stt_ready(self, value: bool) -> None:
        self._stt_ready = value

    @property
    def whisper_model(self) -> Optional[object]:
        return self._whisper_model

    @whisper_model.setter
    def whisper_model(self, model: object) -> None:
        self._whisper_model = model

    @property
    def whisper_lock(self) -> asyncio.Lock:
        return self._whisper_lock


_state: Optional[AppState] = None
_state_lock = threading.Lock()


def get_app_state() -> AppState:
    global _state
    if _state is None:
        with _state_lock:
            if _state is None:
                _state = AppState()
    return _state