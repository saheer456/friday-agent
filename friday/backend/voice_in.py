"""
voice_in.py  —  Always-on VAD microphone listener for FRIDAY.

ContinuousListener runs a background thread that:
  1. Reads mic audio in 30 ms frames via PyAudio
  2. Applies WebRTC VAD per frame
  3. Uses ring-buffer algorithm to detect utterance start / end
  4. Keeps a 300 ms pre-roll so word starts aren't clipped
  5. Transcribes completed utterances with faster-whisper
  6. Puts text into a thread-safe queue — call .get() to read

No silence-timeout hacks. Pure VAD.
"""

import collections
import os
import queue
import tempfile
import threading
import wave

import pyaudio

try:
    import webrtcvad
    _HAS_VAD = True
except ImportError:
    _HAS_VAD = False

# ── Audio constants ───────────────────────────────────────────────────────────
SAMPLE_RATE    = 16_000
FRAME_MS       = 30                                        # 10 / 20 / 30 ms only
FRAME_SAMPLES  = int(SAMPLE_RATE * FRAME_MS / 1_000)      # 480
FRAME_BYTES    = FRAME_SAMPLES * 2                         # int16 = 2 bytes

# ── VAD / utterance tuning ────────────────────────────────────────────────────
VAD_MODE           = 3     # 0=permissive … 3=aggressive (max noise rejection)
START_RING         = 20    # frames in start-ring  (~600 ms)
START_RATIO        = 0.75  # 75% voiced → start collecting (harder to false-trigger)
END_RING           = 30    # frames in end-ring    (~900 ms)
END_RATIO          = 0.92  # 92% silent  → utterance done (less clipping)
PREROLL_FRAMES     = 10    # 300 ms pre-roll before voice trigger
MIN_SPEECH_FRAMES  = 10    # discard blips shorter than 300 ms


# ─────────────────────────────────────────────────────────────────────────────
class ContinuousListener:
    """
    Always-on microphone listener.

    Usage:
        listener = ContinuousListener()
        listener.start()
        ...
        text = listener.get()   # returns None if nothing ready
        ...
        listener.stop()
    """

    def __init__(self, vad_mode: int = VAD_MODE):
        if not _HAS_VAD:
            raise ImportError(
                "webrtcvad not found. Install with:  pip install webrtcvad-wheels"
            )
        self._vad       = webrtcvad.Vad(vad_mode)
        self._whisper   = None                         # lazy-loaded
        self._q: queue.Queue[str] = queue.Queue()
        self._stop      = threading.Event()
        self._thread: threading.Thread | None = None
        self.active     = False
        # Set the MOMENT speech is detected (before transcription).
        # Watchers can interrupt TTS playback immediately.
        self.speech_started = threading.Event()

    # ── Public ────────────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="FRIDAY-VAD"
        )
        self._thread.start()
        self.active = True

    def stop(self):
        self._stop.set()
        self.active = False

    def get(self, timeout: float = 0.05) -> str | None:
        """Non-blocking poll. Returns transcribed text or None."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── Internal ──────────────────────────────────────────────────────────────
    def _load_whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            # "small" is 3x more accurate than "base" — still fast on CPU
            self._whisper = WhisperModel("small", device="cpu", compute_type="int8")
        return self._whisper

    def _listen_loop(self):
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=FRAME_SAMPLES,
        )

        preroll     = collections.deque(maxlen=PREROLL_FRAMES)
        start_ring  = collections.deque(maxlen=START_RING)
        end_ring    = collections.deque(maxlen=END_RING)
        voiced: list[bytes] = []
        triggered   = False

        try:
            while not self._stop.is_set():
                try:
                    frame = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
                except OSError:
                    continue

                is_speech = self._vad.is_speech(frame, SAMPLE_RATE)

                if not triggered:
                    preroll.append(frame)
                    start_ring.append(is_speech)
                    if sum(start_ring) / len(start_ring) >= START_RATIO:
                        triggered = True
                        voiced    = list(preroll)   # include pre-roll
                        end_ring.clear()
                        # ← Fire IMMEDIATELY — stop TTS before transcription
                        self.speech_started.set()
                else:
                    voiced.append(frame)
                    end_ring.append(is_speech)
                    if len(end_ring) == END_RING:
                        silent_ratio = 1.0 - sum(end_ring) / len(end_ring)
                        if silent_ratio >= END_RATIO:
                            triggered = False
                            audio     = b"".join(voiced)
                            voiced    = []
                            end_ring.clear()
                            start_ring.clear()
                            if len(audio) // FRAME_BYTES >= MIN_SPEECH_FRAMES:
                                txt = self._transcribe(audio)
                                # Clear after transcription — watcher can now reset
                                self.speech_started.clear()
                                if txt and len(txt.strip()) > 1:
                                    self._q.put(txt.strip())
                            else:
                                self.speech_started.clear()  # too short — ignore

        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

    def _transcribe(self, pcm: bytes) -> str:
        tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp = tmp_file.name
        tmp_file.close()
        # Prime Whisper with domain vocabulary so it transcribes correctly
        PROMPT = (
            "FRIDAY, sir, RAG system, Groq, Python, cybersecurity, "
            "networking, Kerala, Saheer, open, search, weather, "
            "what is, tell me, can you"
        )
        try:
            with wave.open(tmp, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(pcm)
            model = self._load_whisper()
            segs, _ = model.transcribe(
                tmp,
                language="en",          # force English — faster, more accurate
                beam_size=5,
                initial_prompt=PROMPT,  # primes vocabulary context
                vad_filter=True,        # Whisper's own VAD as second pass
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            return " ".join(s.text for s in segs).strip()
        except Exception:
            return ""
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass



