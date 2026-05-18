import { useState, useCallback } from 'react';
import type { Message, Phase } from '../types/api';
import { authFetch } from '../lib/api';
import { clearLocalMemory, retrieveLocalMemory, saveLocalMemory } from '../lib/localMemory';

interface UseChatOptions {
  limitedMode?: boolean;
}

export function useChat(
  onStatusChange: (status: string, busy: boolean) => void,
  queueTTS: (text: string) => void,
  options: UseChatOptions = {},
) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [phases, setPhases] = useState<Phase[]>([]);
  const [isBusy, setIsBusy] = useState(false);
  const { limitedMode = false } = options;

  const addSystemMessage = useCallback((text: string) => {
    setMessages(prev => [...prev, { id: Date.now().toString(), role: 'assistant', content: text, streaming: false }]);
  }, []);

  const clearChat = useCallback(async () => {
    try {
      if (limitedMode) {
        clearLocalMemory();
      } else {
        await authFetch('/api/clear', { method: 'POST' });
      }
      setMessages([{
        id: Date.now().toString(),
        role: 'assistant',
        content: limitedMode
          ? 'Local demo memory cleared.\nAsk anything when ready.'
          : 'Session cleared, sir.\nAsk anything when ready.',
        streaming: false,
      }]);
      setPhases([]);
      onStatusChange('Online', false);
    } catch {
      onStatusChange('Clear failed', false);
    }
  }, [limitedMode, onStatusChange]);

  const sendMessage = useCallback(async (text: string, isVoiceMode: boolean) => {
    if (!text.trim()) return;

    const userMsgId = `u-${Date.now()}`;
    const aiMsgId   = `a-${Date.now()}`;

    // Add user + empty AI message in one update to avoid race
    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user',      content: text, streaming: false },
      { id: aiMsgId,   role: 'assistant', content: '',   streaming: true  },
    ]);

    setPhases([]);
    setIsBusy(true);
    onStatusChange('Neural pipeline…', true);

    try {
      const endpoint = limitedMode ? '/api/chat/limited/stream' : '/api/chat/stream';
      const payload = limitedMode
        ? { message: text, local_context: retrieveLocalMemory(text) }
        : { message: text, voice_mode: isVoiceMode };
      const res = await authFetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error((await res.text()) || res.statusText);

      const reader  = res.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error('No readable stream');

      let buffer    = '';
      let fullText  = '';
      let sawToken  = false;
      let streamDone = false;

      outer: while (!streamDone) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        let idx: number;
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const raw  = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 2);
          if (!raw.startsWith('data:')) continue;

          const data = raw.slice(5).trim();

          // ── Stream finished ─────────────────────────────────
          if (data === '[DONE]') {
            streamDone = true;
            // Capture fullText in local so functional updater is pure
            const finalText = fullText;
            setMessages(prev =>
              prev.map(m => m.id === aiMsgId ? { ...m, streaming: false, content: finalText } : m)
            );
            if (finalText.trim()) {
              if (limitedMode) saveLocalMemory(text, finalText);
              else queueTTS(finalText);
            }
            break outer;
          }

          // ── Parse SSE event ─────────────────────────────────
          let obj: any;
          try { obj = JSON.parse(data); }
          catch { continue; }

          if (obj.type === 'error') throw new Error(obj.message || 'Stream error');

          if (obj.type === 'phase') {
            setPhases(p => [...p, obj as Phase]);
            onStatusChange(obj.title || 'Working…', true);
          }

          if (obj.type === 'token' && obj.text) {
            // Capture the token text immediately — do NOT reference obj inside the updater
            const chunk = String(obj.text);
            if (!sawToken) {
              sawToken = true;
              setPhases(p => [...p, {
                id: 'stream',
                title: 'Token stream',
                detail: 'Primary language channel open · receiving deltas',
              }]);
            }
            fullText += chunk;
            setMessages(prev =>
              prev.map(m => m.id === aiMsgId ? { ...m, content: m.content + chunk } : m)
            );
          }
        }
      }

      setPhases(p => [...p, {
        id: 'commit',
        title: 'Lattice sealed',
        detail: 'Response materialized · dialogue core synchronized',
      }]);

    } catch (err: any) {
      const msg = err?.message ?? String(err);
      setMessages(prev =>
        prev.map(m => m.id === aiMsgId ? { ...m, content: `⚠️ ${msg}`, streaming: false } : m)
      );
      setPhases(p => [...p, { id: 'fault', title: 'Subsystem fault', detail: msg }]);
    } finally {
      setIsBusy(false);
      onStatusChange('Online', false);
    }
  }, [limitedMode, onStatusChange, queueTTS]);

  return { messages, phases, isBusy, sendMessage, clearChat, addSystemMessage };
}
