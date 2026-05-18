import { useState, useRef, useCallback, useEffect } from 'react';
import { authFetch } from '../lib/api';

declare global {
  interface Window {
    SpeechRecognition: any;
    webkitSpeechRecognition: any;
  }
}

export function useVoice(
  onSpeechComplete: (text: string) => void,
  onInterim?: (text: string) => void,
) {
  const [isRecording, setIsRecording] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);

  const recognitionRef = useRef<any>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioQueueRef = useRef<{ url: string; fallback: string }[]>([]);
  const speakAbortRef = useRef<AbortController | null>(null);
  const finalTranscriptRef = useRef('');
  const onSpeechCompleteRef = useRef(onSpeechComplete);
  const onInterimRef = useRef(onInterim);

  onSpeechCompleteRef.current = onSpeechComplete;
  onInterimRef.current = onInterim;

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) return;

    const recognition = new SpeechRec();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = (e: any) => {
      let interim = '';
      let final = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) {
          final += e.results[i][0].transcript;
        } else {
          interim += e.results[i][0].transcript;
        }
      }
      if (final) {
        finalTranscriptRef.current += final;
      }
      if (interim && onInterimRef.current) {
        onInterimRef.current(finalTranscriptRef.current + interim);
      }
    };

    recognition.onend = () => {
      setIsRecording(false);
      const text = finalTranscriptRef.current.trim();
      finalTranscriptRef.current = '';
      if (text && onSpeechCompleteRef.current) {
        onSpeechCompleteRef.current(text);
      }
    };

    recognition.onerror = () => {
      setIsRecording(false);
      finalTranscriptRef.current = '';
    };

    recognitionRef.current = recognition;

    return () => {
      try { recognition.abort(); } catch {}
      recognitionRef.current = null;
    };
  }, []);

  const toggleRecording = useCallback(() => {
    const rec = recognitionRef.current;
    if (!rec) {
      alert('Speech recognition is not supported in your browser.');
      return;
    }
    if (isRecording) {
      finalTranscriptRef.current = '';
      rec.stop();
    } else {
      setIsRecording(true);
      rec.start();
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
    const ctrl = new AbortController();
    speakAbortRef.current = ctrl;

    try {
      const r = await authFetch('/api/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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

      audio.onended = () => {
        URL.revokeObjectURL(url);
        currentAudioRef.current = null;
        setIsPlaying(false);
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        currentAudioRef.current = null;
        setIsPlaying(false);
      };
    } catch (err: any) {
      if (err.name === 'AbortError') return;
      console.error('[TTS Error]', err);
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
