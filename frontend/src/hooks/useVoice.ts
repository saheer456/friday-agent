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
  const audioCtxRef = useRef<AudioContext | null>(null);
  const animationFrameIdRef = useRef<number | null>(null);
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
    recognition.continuous = true;
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
      if (onInterimRef.current) {
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
      console.warn('Speech recognition is not supported in this browser.');
      return;
    }
    if (isRecording) {
      rec.stop();
    } else {
      finalTranscriptRef.current = '';
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
    if (animationFrameIdRef.current) {
      cancelAnimationFrame(animationFrameIdRef.current);
      animationFrameIdRef.current = null;
    }
    document.documentElement.style.setProperty('--voice-volume', '0');
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

      // Set up Web Audio API Analyser
      if (!audioCtxRef.current) {
        audioCtxRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
      }
      const audioContext = audioCtxRef.current;
      if (audioContext.state === 'suspended') {
        await audioContext.resume();
      }

      const source = audioContext.createMediaElementSource(audio);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyser.connect(audioContext.destination);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      const updateVolume = () => {
        if (!currentAudioRef.current) return;
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          sum += dataArray[i];
        }
        const average = sum / bufferLength;
        document.documentElement.style.setProperty('--voice-volume', String(average));
        animationFrameIdRef.current = requestAnimationFrame(updateVolume);
      };

      const cleanup = () => {
        if (animationFrameIdRef.current) {
          cancelAnimationFrame(animationFrameIdRef.current);
          animationFrameIdRef.current = null;
        }
        document.documentElement.style.setProperty('--voice-volume', '0');
        try {
          source.disconnect();
          analyser.disconnect();
        } catch (e) {
          console.debug('Web Audio API cleanup warning:', e);
        }
        URL.revokeObjectURL(url);
        currentAudioRef.current = null;
        setIsPlaying(false);
      };

      audio.onended = cleanup;
      audio.onerror = cleanup;

      setIsPlaying(true);
      audio.play().then(() => {
        updateVolume();
      }).catch((err) => {
        console.warn('Autoplay blocked or playback error:', err);
        cleanup();
      });
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
