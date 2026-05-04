# Voice System Improvements TODO

## Plan Summary
Implement top quick wins from feedback to fix speech recognition (input) and TTS (output) quality.

## Steps
- [x] 1.1 Upgrade Whisper to 'small' in backend/voice_in.py
- [x] 2.1 Switch TTS VOICE to 'af_bella' in backend/tts.py
- [x] 1.4 Add Whisper VAD params in voice_in.py
- [x] 5.2 Increase VAD END_RATIO to 0.92 in voice_in.py
- [x] 5.1 Enhance clean_for_speech() in tts.py
- [x] Test: Run `python test_voice.py` and `python cli.py` (toggle v, say \"friday test\")
- [x] Quick wins implemented ✓

## Dependent Files
backend/voice_in.py
backend/tts.py

Proceed step-by-step after plan approval.

