import { useState, useRef, useCallback, useEffect } from 'react';
import { authFetch } from '../lib/api';

declare global {
  interface Window {
    SpeechRecognition: any;
    webkitSpeechRecognition: any;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

/** Strip markdown and special syntax before TTS chunking on the frontend. */
function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '')          // code blocks
    .replace(/`[^`]*`/g, '')                  // inline code
    .replace(/\$\$[\s\S]+?\$\$/g, 'an equation')  // LaTeX block
    .replace(/\$[^$\n]+?\$/g, 'a formula')    // LaTeX inline
    .replace(/^#{1,6}\s+/gm, '')              // headings
    .replace(/\*\*([^*]+)\*\*/g, '$1')        // bold
    .replace(/\*([^*]+)\*/g, '$1')            // italic
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // links
    .replace(/^[-*+]\s+/gm, '')              // unordered list bullets
    .replace(/^\d+\.\s+/gm, '')             // ordered list bullets
    .replace(/^>\s*/gm, '')                  // blockquotes
    .replace(/\|[^\n]*/g, '')               // table rows
    .replace(/https?:\S+/g, '')              // bare URLs
    .replace(/\[!(NOTE|TIP|WARNING|CAUTION|IMPORTANT)\]/gi, '')  // callout markers
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Split clean text into chunks at sentence boundaries.
 * Merges short sentences (< MIN_WORDS) with the next one to avoid
 * tiny TTS fetches that waste latency.
 */
const MIN_WORDS = 8;

function splitIntoChunks(text: string): string[] {
  // Split on sentence-ending punctuation followed by a space or end of string
  const raw = text.split(/(?<=[.!?])\s+/);
  const chunks: string[] = [];
  let current = '';
  for (const sentence of raw) {
    if (!sentence.trim()) continue;
    current = current ? `${current} ${sentence}` : sentence;
    if (current.split(' ').length >= MIN_WORDS) {
      chunks.push(current.trim());
      current = '';
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.length ? chunks : [text.trim()];
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────
export function useVoice(
  onSpeechComplete: (text: string) => void,
  onInterim?: (text: string) => void,
) {
  const [isRecording, setIsRecording] = useState(false);
  const [sttSupported, setSttSupported] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);

  // ── STT refs ─────────────────────────────────────────────────
  const recognitionRef = useRef<any>(null);
  const finalTranscriptRef = useRef('');
  const onSpeechCompleteRef = useRef(onSpeechComplete);
  const onInterimRef = useRef(onInterim);
  onSpeechCompleteRef.current = onSpeechComplete;
  onInterimRef.current = onInterim;

  // ── TTS state refs ───────────────────────────────────────────
  /**
   * Generation counter — incremented on every new queueTTS call.
   * All async callbacks check this to bail out if they're stale.
   */
  const generationRef = useRef(0);
  const animationFrameIdRef = useRef<number | null>(null);
  /** Blob URLs to revoke on cleanup */
  const blobUrlsRef = useRef<string[]>([]);
  /** Currently playing Audio element */
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  /** AudioContext — created once and reused */
  const audioCtxRef = useRef<AudioContext | null>(null);
  /** Current analyser node (disconnected and replaced each chunk) */
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  
  /** Queue of pending TTS text chunks and their prefetch promises */
  const queueRef = useRef<{ text: string; urlPromise: Promise<string | null> }[]>([]);
  const isProcessingRef = useRef(false);

  // ── STT setup ────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) { setSttSupported(false); return; }
    setSttSupported(true);

    const recognition = new SpeechRec();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = (e: any) => {
      let interim = '';
      let final = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) final += e.results[i][0].transcript;
        else interim += e.results[i][0].transcript;
      }
      if (final) finalTranscriptRef.current += final;
      if (onInterimRef.current) onInterimRef.current(finalTranscriptRef.current + interim);
    };

    recognition.onend = () => {
      setIsRecording(false);
      const text = finalTranscriptRef.current.trim();
      finalTranscriptRef.current = '';
      if (text && onSpeechCompleteRef.current) onSpeechCompleteRef.current(text);
    };

    recognition.onerror = () => { setIsRecording(false); finalTranscriptRef.current = ''; };

    recognitionRef.current = recognition;
    return () => { try { recognition.abort(); } catch {} recognitionRef.current = null; };
  }, []);

  // ── STT toggle ───────────────────────────────────────────────
  const toggleRecording = useCallback(() => {
    const rec = recognitionRef.current;
    if (!rec) { console.warn('Speech recognition not supported.'); return; }
    if (isRecording) { rec.stop(); }
    else { finalTranscriptRef.current = ''; setIsRecording(true); rec.start(); }
  }, [isRecording]);

  // ── TTS cleanup helper ───────────────────────────────────────
  const _cleanupAudio = useCallback(() => {
    if (animationFrameIdRef.current) {
      cancelAnimationFrame(animationFrameIdRef.current);
      animationFrameIdRef.current = null;
    }
    document.documentElement.style.setProperty('--voice-volume', '0');
    try { sourceRef.current?.disconnect(); analyserRef.current?.disconnect(); } catch {}
    sourceRef.current = null;
    analyserRef.current = null;
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    blobUrlsRef.current.forEach(u => URL.revokeObjectURL(u));
    blobUrlsRef.current = [];
  }, []);

  // ── stopAudio ─────────────────────────────────────────────────
  const stopAudio = useCallback(() => {
    generationRef.current++;       // invalidate all pending callbacks
    _cleanupAudio();
    setIsPlaying(false);
    queueRef.current = [];
    isProcessingRef.current = false;
  }, [_cleanupAudio]);

  // ── Fetch a single chunk → blob URL ──────────────────────────
  const _fetchChunk = useCallback(async (chunk: string, gen: number): Promise<string | null> => {
    if (generationRef.current !== gen) return null;
    try {
      const r = await authFetch('/api/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: chunk }),
      });
      if (generationRef.current !== gen) return null;
      if (!r.ok) throw new Error(`speak ${r.status}`);
      const blob = await r.blob();
      if (generationRef.current !== gen) return null;
      const url = URL.createObjectURL(blob);
      blobUrlsRef.current.push(url);
      return url;
    } catch {
      return null;
    }
  }, []);

  // ── Play a chunk URL, returns a promise that resolves on 'ended' ──
  const _playUrl = useCallback(async (url: string, gen: number): Promise<void> => {
    return new Promise((resolve) => {
      if (generationRef.current !== gen) { resolve(); return; }

      // Get/create AudioContext (reused)
      if (!audioCtxRef.current) {
        audioCtxRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
      }
      const ctx = audioCtxRef.current;

      // Each chunk gets a FRESH Audio element — avoids createMediaElementSource() throw
      const audio = new Audio(url);
      currentAudioRef.current = audio;

      const done = () => {
        try { sourceRef.current?.disconnect(); analyserRef.current?.disconnect(); } catch {}
        sourceRef.current = null;
        analyserRef.current = null;
        if (animationFrameIdRef.current) {
          cancelAnimationFrame(animationFrameIdRef.current);
          animationFrameIdRef.current = null;
        }
        document.documentElement.style.setProperty('--voice-volume', '0');
        resolve();
      };

      audio.onended = done;
      audio.onerror = done;

      const startPlayback = async () => {
        if (generationRef.current !== gen) { resolve(); return; }
        if (ctx.state === 'suspended') await ctx.resume();

        try {
          const source = ctx.createMediaElementSource(audio);
          const analyser = ctx.createAnalyser();
          analyser.fftSize = 256;
          source.connect(analyser);
          analyser.connect(ctx.destination);
          sourceRef.current = source;
          analyserRef.current = analyser;

          const data = new Uint8Array(analyser.frequencyBinCount);
          const tick = () => {
            if (!currentAudioRef.current || generationRef.current !== gen) return;
            analyser.getByteFrequencyData(data);
            const avg = data.reduce((a, b) => a + b, 0) / data.length;
            document.documentElement.style.setProperty('--voice-volume', String(avg));
            animationFrameIdRef.current = requestAnimationFrame(tick);
          };

          await audio.play();
          tick();
        } catch (err) {
          console.warn('[TTS] Playback error:', err);
          resolve();
        }
      };

      startPlayback();
    });
  }, []);

  // ── Playback loop ─────────────────────────────────────────────
  const _runPlaybackLoop = useCallback(async (gen: number) => {
    if (isProcessingRef.current) return;
    isProcessingRef.current = true;
    setIsPlaying(true);

    try {
      while (generationRef.current === gen) {
        if (queueRef.current.length > 0) {
          const item = queueRef.current.shift()!;
          const url = await item.urlPromise;
          if (url && generationRef.current === gen) {
            await _playUrl(url, gen);
          }
        } else {
          setIsPlaying(false);
          break;
        }
      }
    } finally {
      isProcessingRef.current = false;
    }
  }, [_playUrl]);

  // ── queueTTS — main entry point ───────────────────────────────
  const queueTTS = useCallback(async (fullText: string) => {
    const clean = stripMarkdown(fullText);
    if (!clean) return;

    const chunks = splitIntoChunks(clean);
    if (!chunks.length) return;

    // If starting fresh, increment generation to cancel any background stale tasks
    if (!isProcessingRef.current && queueRef.current.length === 0) {
      generationRef.current++;
    }
    const gen = generationRef.current;

    // Create queue items and start prefetching immediately
    const items = chunks.map(chunk => ({
      text: chunk,
      urlPromise: _fetchChunk(chunk, gen)
    }));

    queueRef.current.push(...items);

    // Run playback loop
    if (!isProcessingRef.current) {
      _runPlaybackLoop(gen);
    }
  }, [_fetchChunk, _runPlaybackLoop]);

  return {
    isRecording,
    isPlaying,
    toggleRecording,
    stopAudio,
    queueTTS,
    sttSupported,
  };
}
