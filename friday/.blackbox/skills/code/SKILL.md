---
name: code
description: Improve and troubleshoot voice assistant components (VAD, Whisper, TTS) for the "Friday" RAG system. Includes microphone privacy fixes, model tuning, and Windows/PowerShell environment setup.
---

# Code

## Instructions

1. **Verify microphone privacy settings**  
   - Ensure `Windows Settings → Privacy → Microphone → Allow apps` is enabled.  
   - If the wake word is not detected (90% chance from tests), re-check this setting and audio device permissions.

2. **Tune Voice Activity Detection (VAD)**  
   - In `voice_in.py`, adjust `END_RATIO` from 0.85 → 0.92 to prevent clipped sentence endings.  
   - Add debug prints inside `__listen_loop` to log VAD statistics (speech duration, noise floor).  
   - Set VAD mode via environment variable (e.g., `VAD_MODE=3` for most aggressive).

3. **Upgrade Whisper transcription**  
   - Change model from `base` → `small` in `voice_in.py` for ~15–20% better accuracy (numbers, domain terms).  
   - If using `faster-whisper`, enable `noise_reduction=True` in the transcribe call to reduce background hiss.

4. **Improve Text-to-Speech voice**  
   - In `tts.py`, change `VOICE = "bf_emma"` → `VOICE = "af_bella"` for more natural intonation.

5. **Fix common Python import errors (PowerShell)**  
   - The command `python -c "\import webrtcvad; print('webrtcvad OK')"` fails due to backslash escaping.  
   - Use double quotes inside single quotes or escape properly:  
     ```powershell
     python -c "import webrtcvad; print('webrtcvad OK')"