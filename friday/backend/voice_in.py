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
import math

import pyaudio
import numpy as np
from scipy import signal

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

# High-pass filter to remove room rumble (< 80Hz)
SOS_FILTER = signal.butter(4, 80, 'hp', fs=SAMPLE_RATE, output='sos')

# ── VAD / utterance tuning ────────────────────────────────────────────────────
VAD_MODE           = 3     # 0=permissive … 3=aggressive (max noise rejection)
START_RING         = 20    # frames in start-ring  (~600 ms)
START_RATIO        = 0.75  # 75% voiced → start collecting (harder to false-trigger)
END_RING           = 30    # frames in end-ring    (~900 ms)
END_RATIO          = 0.92  # 92% silent  → utterance done (less clipping)
PREROLL_FRAMES     = 10    # 300 ms pre-roll before voice trigger
MIN_SPEECH_FRAMES  = 10    # discard blips shorter than 300 ms


# ─────────────────────────────────────────────────────────────────────────────
class MicrophoneHealthCheck:
    """Detect bad mics, USB glitches, and measure room noise floor."""
    @staticmethod
    def check_mic_levels(frames: list[bytes]) -> dict:
        import numpy as np
        levels = []
        for frame in frames:
            audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
            level = np.sqrt(np.mean(audio ** 2))
            levels.append(level)
        
        avg_level = np.mean(levels)
        peak = np.max(levels)
        
        return {
            "avg_db": 20 * np.log10(max(avg_level, 1e-5)),
            "peak_db": 20 * np.log10(max(peak, 1e-5)),
            "clipping": peak > 0.99,
            "silent": avg_level < 0.001,
            "status": "OK" if 0.001 < avg_level < 0.5 else "WARN",
            "noise_floor": float(np.percentile(levels, 25))
        }

    @staticmethod
    def detect_echo(speaker_output: bytes, mic_input: bytes) -> float:
        """Cross-correlation to detect echo (requires shared memory buffer sync)"""
        import numpy as np
        from scipy import signal
        
        speaker = np.frombuffer(speaker_output, dtype=np.int16).astype(np.float32)
        mic = np.frombuffer(mic_input, dtype=np.int16).astype(np.float32)
        
        if len(speaker) > len(mic):
            speaker = speaker[:len(mic)]
        elif len(mic) > len(speaker):
            mic = mic[:len(speaker)]
            
        if len(speaker) == 0 or np.sum(speaker) == 0 or np.sum(mic) == 0:
            return 0.0
            
        correlation = np.correlate(mic, speaker, mode='full')
        correlation = correlation / (np.linalg.norm(speaker) * np.linalg.norm(mic) + 1e-8)
        
        return float(np.max(correlation))  # 0-1 score

# ─────────────────────────────────────────────────────────────────────────────
class SpeakerDiarization:
    """Identify if user or others speaking using basic FFT profiling."""
    
    def __init__(self):
        self.baseline_voice_profile = None  # Learn user's voice
    
    def learn_speaker(self, audio: bytes):
        """Fingerprint speaker voice (assumes first speaker is user)"""
        import numpy as np
        from scipy.fft import fft
        
        arr = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
        fft_result = np.abs(fft(arr))
        # Protect against empty arrays or zero sum
        if len(fft_result) == 0 or np.sum(fft_result) == 0:
            return
            
        centroid = np.average(
            np.arange(len(fft_result)),
            weights=fft_result
        )
        
        if self.baseline_voice_profile is None:
            self.baseline_voice_profile = {
                "centroid": centroid,
                "energy": np.sqrt(np.mean(arr ** 2))
            }
            print("[VAD] Baseline voice profile locked.")
    
    def identify_speaker(self, audio: bytes) -> dict:
        """Check if voice matches known user"""
        import numpy as np
        from scipy.fft import fft
        
        if not self.baseline_voice_profile:
            return {"speaker": "unknown", "confidence": 0.0}
        
        arr = np.frombuffer(audio, dtype=np.int16).astype(np.float32)
        fft_result = np.abs(fft(arr))
        if len(fft_result) == 0 or np.sum(fft_result) == 0:
            return {"speaker": "unknown", "confidence": 0.0}
            
        centroid = np.average(
            np.arange(len(fft_result)),
            weights=fft_result
        )
        energy = np.sqrt(np.mean(arr ** 2))
        
        # Compare to baseline
        centroid_diff = abs(centroid - self.baseline_voice_profile["centroid"])
        energy_diff = abs(energy - self.baseline_voice_profile["energy"])
        
        confidence = 1.0 - min(1.0, centroid_diff / 1000 + energy_diff / 100)
        
        return {
            "speaker": "user" if confidence > 0.7 else "other",
            "confidence": confidence
        }

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
        self._filter_state = signal.sosfilt_zi(SOS_FILTER)
        self.dynamic_threshold = 0.005  # initial default, updated after calibration
        self.diarization = SpeakerDiarization()
        self.latest_frame = b""
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

    def _preprocess_audio(self, frame: bytes) -> bytes:
        """Apply noise gate + light filtering with state retention."""
        # Convert bytes → float32 array
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        
        # 1. Noise gate - mute very quiet frames (reduces background hum)
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < self.dynamic_threshold:  # threshold - tune per environment
            return np.zeros_like(audio).astype(np.int16).tobytes()
        
        # 2. High-pass filter (removes room noise, rumble)
        audio, self._filter_state = signal.sosfilt(SOS_FILTER, audio, zi=self._filter_state)
        
        # 3. Normalize to -3dB to avoid clipping
        peak = np.max(np.abs(audio))
        if peak > 0:
            audio = (audio / peak) * 0.707
        
        return (audio * 32768).astype(np.int16).tobytes()

    # ── Internal ──────────────────────────────────────────────────────────────
    def _load_whisper(self):
        if self._whisper is None:
            from faster_whisper import WhisperModel
            # "small" is slower than "base" but gives noticeably better command accuracy.
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

        # ── Calibration & Health Check ──
        print("[VAD] Calibrating microphone... Please remain quiet for 3 seconds.")
        calibration_frames = []
        try:
            for _ in range(100):  # ~3 seconds
                frame = stream.read(FRAME_SAMPLES, exception_on_overflow=False)
                calibration_frames.append(frame)
                
            health = MicrophoneHealthCheck.check_mic_levels(calibration_frames)
            
            status_color = "\033[91m" if health["status"] == "WARN" else "\033[92m"
            print(f"[VAD] Mic health: {status_color}{health['status']}\033[0m "
                  f"(Avg: {health['avg_db']:.1f}dB, Peak: {health['peak_db']:.1f}dB)")
            if health["clipping"]:
                print("[VAD] WARNING: Microphone is clipping. Please lower input volume.")
            if health["silent"]:
                print("[VAD] WARNING: Microphone is silent. Check your connection.")
                
            # Adaptive threshold: trigger at 3x the 25th percentile noise floor
            self.dynamic_threshold = max(0.001, health["noise_floor"] * 3)
            print(f"[VAD] Calibrated dynamic noise gate to: {self.dynamic_threshold:.5f}")
        except Exception as e:
            print(f"[VAD] Calibration failed: {e}")

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

                # Preprocess frame before VAD to improve noise rejection
                processed_frame = self._preprocess_audio(frame)
                self.latest_frame = processed_frame
                is_speech = self._vad.is_speech(processed_frame, SAMPLE_RATE)

                if not triggered:
                    preroll.append(processed_frame)
                    start_ring.append(is_speech)
                    if sum(start_ring) / len(start_ring) >= START_RATIO:
                        triggered = True
                        voiced    = list(preroll)   # include pre-roll
                        end_ring.clear()
                        # ← Fire IMMEDIATELY — stop TTS before transcription
                        self.speech_started.set()
                else:
                    voiced.append(processed_frame)
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
                                # Speaker Diarization
                                if not self.diarization.baseline_voice_profile:
                                    self.diarization.learn_speaker(audio)
                                    speaker = "user"
                                else:
                                    res = self.diarization.identify_speaker(audio)
                                    speaker = res["speaker"]
                                
                                txt = self._transcribe(audio)
                                # Clear after transcription — watcher can now reset
                                self.speech_started.clear()
                                if txt and len(txt.strip()) > 1:
                                    if speaker == "other":
                                        txt = f"[Unknown Speaker] {txt}"
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
            segs = list(segs)
            if not segs:
                return ""
                
            # Confidence scoring
            avg_prob = sum(math.exp(s.avg_logprob) for s in segs) / len(segs)
            if avg_prob < 0.6:
                print(f"[VAD] Dropped low-confidence transcription ({avg_prob:.2f})")
                return ""
                
            return " ".join(s.text for s in segs).strip()
        except Exception:
            return ""
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

