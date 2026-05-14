import { useState, useRef, useCallback, useEffect } from 'react';

// For SpeechRecognition types
declare global {
  interface Window {
    SpeechRecognition: any;
    webkitSpeechRecognition: any;
  }
}

export function useVoice(onSpeechComplete: (text: string) => void) {
  const [isRecording, setIsRecording] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  
  const recognitionRef = useRef<any>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioQueueRef = useRef<{ url: string; fallback: string }[]>([]);
  const speakAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SpeechRec) {
        recognitionRef.current = new SpeechRec();
        recognitionRef.current.continuous = false;
        recognitionRef.current.interimResults = true;
        
        // Let the parent component handle interim/final via a custom callback
        // or just fire when it ends. To keep it simple, we'll fire on end if we have text.
        // Actually, the vanilla version updated the input *during* speech. 
        // We'll pass a separate callback for interim results if we want that.
        // Let's just handle final results.
        
        let finalTranscript = '';
        recognitionRef.current.onresult = (e: any) => {
          let interim = '';
          finalTranscript = '';
          for (let i = e.resultIndex; i < e.results.length; ++i) {
            if (e.results[i].isFinal) finalTranscript += e.results[i][0].transcript;
            else interim += e.results[i][0].transcript;
          }
          // If you wanted live updates in the input, you'd pass an `onInterim` callback.
          // We'll simulate the vanilla app's behavior by passing the final string.
        };

        recognitionRef.current.onend = () => {
          setIsRecording(false);
          if (finalTranscript.trim()) {
            onSpeechComplete(finalTranscript);
          }
        };
      }
    }
  }, [onSpeechComplete]);

  const toggleRecording = useCallback(() => {
    if (!recognitionRef.current) {
      alert("Speech recognition is not supported in your browser.");
      return;
    }
    if (isRecording) {
      recognitionRef.current.stop();
    } else {
      setIsRecording(true);
      recognitionRef.current.start();
    }
  }, [isRecording]);

  const stopAudio = useCallback(() => {
    if (speakAbortRef.current) {
      speakAbortRef.current.abort();
      speakAbortRef.current = null;
    }
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    audioQueueRef.current.forEach(({ url }) => URL.revokeObjectURL(url));
    audioQueueRef.current = [];
    setIsPlaying(false);
  }, []);

  const queueTTS = useCallback(async (fullText: string) => {
    // This replicates the `_speakAbort` logic from app.js
    const ctrl = new AbortController();
    speakAbortRef.current = ctrl;

    try {
      const r = await fetch("/api/speak", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: fullText }),
        signal: ctrl.signal,
      });

      if (!r.ok) throw new Error(`speak ${r.status}`);
      const blob = await r.blob();
      
      if (ctrl.signal.aborted) return;
      
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      currentAudioRef.current = audio;
      speakAbortRef.current = null;
      
      setIsPlaying(true);
      audio.play();
      
      audio.onended = () => { URL.revokeObjectURL(url); currentAudioRef.current = null; setIsPlaying(false); };
      audio.onerror = () => { URL.revokeObjectURL(url); currentAudioRef.current = null; setIsPlaying(false); };
    } catch (err: any) {
      if (err.name === "AbortError") return;
      console.error("[TTS Error]", err);
      setIsPlaying(false);
    }
  }, []);

  return {
    isRecording,
    isPlaying,
    toggleRecording,
    stopAudio,
    queueTTS,
  };
}
