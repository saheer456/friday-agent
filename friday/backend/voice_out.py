"""
voice_out.py
Text-to-speech using piper-tts and sounddevice, running in a background thread.
"""
import re
import threading
import subprocess
import os

def clean_text_for_speech(text: str) -> str:
    """Removes markdown and URLs before speaking."""
    # Remove code blocks
    text = re.sub(r'```.*?```', ' code block ', text, flags=re.DOTALL)
    # Remove inline code
    text = re.sub(r'`.*?`', '', text)
    # Remove URLs
    text = re.sub(r'http\S+', '', text)
    # Remove markdown bold/italic
    text = re.sub(r'[*_]{1,2}', '', text)
    # Remove markdown links
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    # Remove special characters that might sound weird
    text = re.sub(r'[#>]', '', text)
    return text.strip()

def _speak_thread(text: str):
    """Internal function to run piper-tts."""
    cleaned = clean_text_for_speech(text)
    if not cleaned:
        return
        
    try:
        import soundfile as sf
        import sounddevice as sd
        import tempfile

        voice_model = os.getenv("VOICE_MODEL", "en_US-lessac-medium")
        
        # Use a unique temp file per call to avoid conflicts with concurrent TTS calls
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        cmd_wav = [
            "piper",
            "--model", f"{voice_model}.onnx",
            "--output_file", wav_path
        ]
        
        process = subprocess.Popen(
            cmd_wav,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        out, err = process.communicate(input=cleaned)
        
        if process.returncode == 0 and os.path.exists(wav_path):
            data, fs = sf.read(wav_path)
            sd.play(data, fs)
            sd.wait()
        else:
            print(f"Piper TTS Error: {err}")

        # Clean up wav file
        if os.path.exists(wav_path):
            os.remove(wav_path)
            
    except Exception as e:
        print(f"Error in voice_out: {e}")

def speak(text: str):
    """Speaks text in a background thread to prevent blocking UI/Backend."""
    t = threading.Thread(target=_speak_thread, args=(text,))
    t.daemon = True
    t.start()
