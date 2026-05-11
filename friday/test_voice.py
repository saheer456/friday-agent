#!/usr/bin/env python3
"""Quick test for voice input: records until silence, transcribes, prints result."""

from backend.voice_in import record_audio, transcribe_audio
import os

print("Speak now (stops on silence)...")
audio_file = record_audio()
print(f"Recorded: {audio_file}")
print(f"Transcript: {transcribe_audio(audio_file)}")
print("Test complete. Delete temp file if needed.")

