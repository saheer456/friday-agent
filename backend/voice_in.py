"""
voice_in.py — VAD microphone listener + live partial STT + final Whisper.

- WebRTC VAD for utterance boundaries (tunable via FRIDAY_VAD_MODE).
- faster-whisper: periodic partial transcripts while speaking (live STT).
- Final pass on silence with higher beam width; no nested Whisper VAD.
- Optional echo skip using int16 mono 16 kHz reference from TTS.
- Optional VoicePipelineModel for Rich dashboard hooks.
"""

from __future__ import annotations

import collections
import math
import os
import queue
import tempfile
import threading
import time
import wave

import numpy as np
import pyaudio
from scipy import signal

try:
    import webrtcvad

    _HAS_VAD = True
except ImportError:
    _HAS_VAD = False

from backend.voice_state import PipelineStage, VoicePipelineModel

# ── Audio constants ───────────────────────────────────────────────────────────
SAMPLE_RATE = 16_000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1_000)
FRAME_BYTES = FRAME_SAMPLES * 2

SOS_FILTER = signal.butter(4, 80, "hp", fs=SAMPLE_RATE, output="sos")

VAD_MODE = int(os.getenv("FRIDAY_VAD_MODE", "2"))
START_RING = int(os.getenv("FRIDAY_VAD_START_RING", "18"))
START_RATIO = float(os.getenv("FRIDAY_VAD_START_RATIO", "0.72"))
END_RING = int(os.getenv("FRIDAY_VAD_END_RING", "28"))
END_RATIO = float(os.getenv("FRIDAY_VAD_END_RATIO", "0.90"))
PREROLL_FRAMES = int(os.getenv("FRIDAY_VAD_PREROLL", "10"))
MIN_SPEECH_FRAMES = int(os.getenv("FRIDAY_VAD_MIN_SPEECH_FRAMES", "8"))

WHISPER_MODEL = os.getenv("FRIDAY_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("FRIDAY_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("FRIDAY_WHISPER_COMPUTE", "int8")
PARTIAL_INTERVAL_S = float(os.getenv("FRIDAY_STT_PARTIAL_INTERVAL", "0.85"))
PARTIAL_MAX_SECONDS = float(os.getenv("FRIDAY_STT_PARTIAL_MAX_SEC", "5.0"))
STT_DROP_THRESHOLD = float(os.getenv("FRIDAY_STT_MIN_HYBRID", "0.38"))


class MicrophoneHealthCheck:
    @staticmethod
    def check_mic_levels(frames: list[bytes]) -> dict:
        levels = []
        for frame in frames:
            audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
            level = float(np.sqrt(np.mean(audio**2)))
            levels.append(level)
        avg_level = float(np.mean(levels))
        peak = float(np.max(levels))
        return {
            "avg_db": 20 * np.log10(max(avg_level, 1e-5)),
            "peak_db": 20 * np.log10(max(peak, 1e-5)),
            "clipping": peak > 0.99,
            "silent": avg_level < 0.001,
            "status": "OK" if 0.001 < avg_level < 0.5 else "WARN",
            "noise_floor": float(np.percentile(levels, 25)),
        }

    @staticmethod
    def detect_echo(speaker_pcm16: bytes, mic_pcm16: bytes) -> float:
        if len(speaker_pcm16) < 320 or len(mic_pcm16) < len(speaker_pcm16):
            return 0.0
        sp = np.frombuffer(speaker_pcm16[:960], dtype=np.int16).astype(np.float32)
        mc = np.frombuffer(mic_pcm16[: len(sp)], dtype=np.int16).astype(np.float32)
        if sp.size == 0 or mc.size == 0:
            return 0.0
        if np.linalg.norm(sp) < 1e-3 or np.linalg.norm(mc) < 1e-3:
            return 0.0
        corr = np.correlate(mc, sp, mode="valid")
        corr = corr / (np.linalg.norm(sp) * np.linalg.norm(mc) + 1e-8)
        return float(np.max(corr)) if corr.size else 0.0


class _PartialSTTWorker(threading.Thread):
    """Serializes partial Whisper runs off the capture hot path."""

    def __init__(self, owner: "ContinuousListener"):
        super().__init__(daemon=True, name="FRIDAY-Partial-STT")
        self._owner = owner
        self._q: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
        self._stop = threading.Event()

    def submit_audio(self, pcm: bytes):
        if self._stop.is_set() or not pcm:
            return
        try:
            while True:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
        except Exception:
            pass
        try:
            self._q.put_nowait(pcm)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(pcm)
            except queue.Full:
                pass

    def shutdown(self):
        self._stop.set()
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass

    def run(self):
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                text = self._owner._transcribe_partial(item)
                if text and self._owner._viz:
                    self._owner._viz.set_live_stt(text)
                    self._owner._viz.set_stage(PipelineStage.STT_LIVE)
                    self._owner._viz.bump_partial()
            except Exception as e:
                if self._owner._viz:
                    self._owner._viz.set_error(f"partial STT: {e}")


class ContinuousListener:
    def __init__(
        self,
        vad_mode: int = VAD_MODE,
        viz: VoicePipelineModel | None = None,
    ):
        if not _HAS_VAD:
            raise ImportError("webrtcvad not found. Install: pip install webrtcvad-wheels")
        self._vad = webrtcvad.Vad(vad_mode)
        self._whisper = None
        self._q: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.active = False
        self._filter_state = signal.sosfilt_zi(SOS_FILTER)
        self.dynamic_threshold = 0.005
        self.latest_frame = b""
        self.tts_reference_frame = b""
        self._utterance_count = 0
        self._last_transcription_ms = 0.0
        self.speech_started = threading.Event()
        self._viz = viz
        self._partial: _PartialSTTWorker | None = None
        self._last_partial_mono = 0.0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if self._viz:
            self._viz.set_whisper_model(WHISPER_MODEL)
        self._partial = _PartialSTTWorker(self)
        self._partial.start()
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="FRIDAY-VAD")
        self._thread.start()
        self.active = True

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)
        self._thread = None
        if self._partial:
            self._partial.shutdown()
            self._partial.join(timeout=4.0)
            self._partial = None
        self.active = False

    def get(self, timeout: float = 0.05) -> str | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def _preprocess_audio(self, frame: bytes) -> bytes:
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(audio**2)))
        if self._viz:
            self._viz.set_input_level(min(1.0, rms * 25.0))
        if rms < self.dynamic_threshold:
            zeros = np.zeros_like(audio)
            _, self._filter_state = signal.sosfilt(SOS_FILTER, zeros, zi=self._filter_state)
            return zeros.astype(np.int16).tobytes()
        audio, self._filter_state = signal.sosfilt(SOS_FILTER, audio, zi=self._filter_state)
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = (audio / peak) * 0.707
        return (audio * 32768).astype(np.int16).tobytes()

    def _load_whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel

            self._whisper = WhisperModel(
                WHISPER_MODEL,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE,
            )
        return self._whisper

    @staticmethod
    def _domain_prompt() -> str:
        return (
            "FRIDAY, sir, RAG system, Groq, Python, cybersecurity, "
            "networking, Kerala, Saheer, open, search, weather, "
            "what is, tell me, can you"
        )

    def _transcribe_partial(self, pcm: bytes) -> str:
        if len(pcm) < FRAME_BYTES * 12:
            return ""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        path = tmp.name
        tmp.close()
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(pcm)
            model = self._load_whisper()
            segs, _ = model.transcribe(
                path,
                language="en",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                vad_filter=False,
                without_timestamps=True,
                word_timestamps=False,
                condition_on_previous_text=True,
                initial_prompt=self._domain_prompt(),
                compression_ratio_threshold=2.8,
                log_prob_threshold=-1.2,
                no_speech_threshold=0.5,
            )
            segs = list(segs)
            if not segs:
                return ""
            return " ".join(s.text for s in segs).strip()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _transcribe_final(self, pcm: bytes) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        path = tmp.name
        tmp.close()
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(pcm)
            model = self._load_whisper()
            segs, _ = model.transcribe(
                path,
                language="en",
                beam_size=5,
                initial_prompt=self._domain_prompt(),
                vad_filter=False,
                temperature=0.0,
                compression_ratio_threshold=2.6,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.6,
            )
            segs = list(segs)
            if not segs:
                return ""
            avg_prob = sum(math.exp(s.avg_logprob) for s in segs) / len(segs)
            avg_cr = sum(s.compression_ratio for s in segs) / len(segs)
            cr_penalty = max(0.0, (avg_cr - 1.85) / 2.0)
            hybrid_score = avg_prob * (1.0 - min(0.45, cr_penalty))
            if hybrid_score < STT_DROP_THRESHOLD:
                print(
                    f"[STT] Dropped borderline (prob={avg_prob:.2f} cr={avg_cr:.2f} score={hybrid_score:.2f})"
                )
                return ""
            return " ".join(s.text for s in segs).strip()
        except Exception as e:
            print(f"[STT] Final transcription error: {e}")
            if self._viz:
                self._viz.set_error(str(e))
            return ""
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _listen_loop(self):
        if self._viz:
            self._viz.set_stage(PipelineStage.CALIBRATING)
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=FRAME_SAMPLES,
        )

        print("[VAD] Calibrating microphone... Please remain quiet for ~3 seconds.")
        calibration_frames: list[bytes] = []
        try:
            for _ in range(100):
                frame = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
                calibration_frames.append(frame)
            health = MicrophoneHealthCheck.check_mic_levels(calibration_frames)
            status_color = "\033[91m" if health["status"] == "WARN" else "\033[92m"
            print(
                f"[VAD] Mic health: {status_color}{health['status']}\033[0m "
                f"(Avg: {health['avg_db']:.1f}dB, Peak: {health['peak_db']:.1f}dB)"
            )
            if health["clipping"]:
                print("[VAD] WARNING: Microphone is clipping. Lower input volume.")
            if health["silent"]:
                print("[VAD] WARNING: Microphone is silent. Check your connection.")
            self.dynamic_threshold = max(0.001, health["noise_floor"] * 3)
            print(f"[VAD] Calibrated dynamic noise gate to: {self.dynamic_threshold:.5f}")
        except Exception as e:
            print(f"[VAD] Calibration failed: {e}")
            if self._viz:
                self._viz.set_error(f"calibration: {e}")

        if self._viz:
            self._viz.clear_error()
            self._viz.set_stage(PipelineStage.LISTENING)

        preroll = collections.deque(maxlen=PREROLL_FRAMES)
        start_ring = collections.deque(maxlen=START_RING)
        end_ring = collections.deque(maxlen=END_RING)
        voiced: list[bytes] = []
        triggered = False

        max_partial_bytes = int((PARTIAL_MAX_SECONDS * 1000 / FRAME_MS) * FRAME_BYTES)

        try:
            while not self._stop.is_set():
                try:
                    frame = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
                except OSError:
                    continue

                processed_frame = self._preprocess_audio(frame)
                self.latest_frame = processed_frame
                is_speech = self._vad.is_speech(processed_frame, SAMPLE_RATE)

                if not triggered:
                    preroll.append(processed_frame)
                    start_ring.append(is_speech)
                    if len(start_ring) == START_RING and sum(start_ring) / len(start_ring) >= START_RATIO:
                        triggered = True
                        voiced = list(preroll)
                        end_ring.clear()
                        self.speech_started.set()
                        if self._viz:
                            self._viz.set_stage(PipelineStage.SPEECH_ONSET)
                        self._last_partial_mono = time.monotonic()
                else:
                    voiced.append(processed_frame)
                    end_ring.append(is_speech)

                    now = time.monotonic()
                    if now - self._last_partial_mono >= PARTIAL_INTERVAL_S:
                        self._last_partial_mono = now
                        chunk = b"".join(voiced)
                        if len(chunk) > max_partial_bytes:
                            chunk = chunk[-max_partial_bytes:]
                        if self._partial:
                            self._partial.submit_audio(chunk)

                    if len(end_ring) == END_RING:
                        silent_ratio = 1.0 - sum(end_ring) / len(end_ring)
                        if silent_ratio >= END_RATIO:
                            triggered = False
                            audio = b"".join(voiced)
                            voiced = []
                            end_ring.clear()
                            start_ring.clear()
                            self.speech_started.clear()
                            if self._viz:
                                self._viz.set_stage(PipelineStage.STT_FINAL)

                            if len(audio) // FRAME_BYTES < MIN_SPEECH_FRAMES:
                                if self._viz:
                                    self._viz.clear_live_stt()
                                    self._viz.set_stage(PipelineStage.LISTENING)
                                continue

                            if self.tts_reference_frame and len(self.tts_reference_frame) >= 320:
                                ref = self.tts_reference_frame[:960]
                                echo_score = MicrophoneHealthCheck.detect_echo(ref, audio[: len(ref)])
                                if echo_score > 0.78:
                                    print(f"[VAD] Echo detected ({echo_score:.2f}) — skipping utterance.")
                                    if self._viz:
                                        self._viz.clear_live_stt()
                                        self._viz.set_stage(PipelineStage.LISTENING)
                                    continue

                            t0 = time.perf_counter()
                            txt = self._transcribe_final(audio)
                            self._last_transcription_ms = (time.perf_counter() - t0) * 1000
                            self._utterance_count += 1
                            if self._viz:
                                self._viz.set_final_stt(txt, self._last_transcription_ms)
                                self._viz.set_stage(PipelineStage.LISTENING)
                                self._viz.clear_live_stt()

                            if txt and len(txt.strip()) > 1:
                                self._q.put(txt.strip())
                            elif self._viz:
                                self._viz.set_error("empty final transcript")

        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
