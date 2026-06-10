import { useState, useCallback, useRef } from 'react';
import type { Message, Phase } from '../types/api';
import { authFetch } from '../lib/api';
import { clearLocalMemory, retrieveLocalMemory, saveLocalMemory } from '../lib/localMemory';

function isSpeakable(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (trimmed.startsWith('```') || trimmed.endsWith('```')) return false;
  if (trimmed.includes('|') && (trimmed.includes('---') || trimmed.includes('-|-'))) return false;
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) return false;
  if (/["'][a-zA-Z0-9_-]+["']\s*:/i.test(trimmed)) return false;
  if (/^(import|const|let|var|function|class|def|return|from|public|private|async|await)\s/i.test(trimmed)) return false;
  if (/^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph)\b/i.test(trimmed)) return false;
  if (trimmed.includes('-->') || trimmed.includes('---') || trimmed.includes('==>')) return false;
  const letters = trimmed.replace(/[^a-zA-Z0-9]/g, '').length;
  if (letters === 0) return false;
  if (trimmed.length > 10 && letters / trimmed.length < 0.4) return false;
  const words = trimmed.split(/\s+/).filter(w => w.length > 0);
  if (words.length < 2) {
    if (!/^[a-zA-Z]{2,15}$/.test(trimmed)) return false;
  }
  return true;
}

function parseCreatedAt(raw?: string): string | undefined {
  if (!raw) return undefined;
  const normalized = raw.includes(' ') && !raw.includes('T') && !raw.includes('Z')
    ? raw.replace(' ', 'T') + 'Z'
    : raw;
  const d = new Date(normalized);
  return isNaN(d.getTime()) ? undefined : d.toISOString();
}

export function useStreaming(
  onStatusChange: (status: string, busy: boolean) => void,
  queueTTS: (text: string) => void,
  limitedMode: boolean,
) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [phases, setPhases] = useState<Phase[]>([]);
  const [isBusy, setIsBusy] = useState(false);
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const [isLoadingSession, setIsLoadingSession] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const fetchGenRef = useRef(0);
  const messagesCursorRef = useRef<number | undefined>(undefined);
  const firstMsgSentRef = useRef(false);
  const activeSessionIdRef = useRef('');

  const addSystemMessage = useCallback((text: string) => {
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    setMessages(prev => [...prev, {
      id: Date.now().toString(),
      role: 'assistant',
      content: text,
      streaming: false,
      timestamp: timeStr,
      createdAt: now.toISOString(),
    }]);
  }, []);

  const mapDbMessage = useCallback((m: { id?: number; role: string; content: string; created_at?: string }, sessionId: string, idx: number) => {
    const createdAt = parseCreatedAt(m.created_at);
    const d = createdAt ? new Date(createdAt) : new Date();
    const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    return {
      id: typeof m.id === 'number' ? `db-${m.id}` : `m-${sessionId}-${idx}`,
      role: m.role as Message['role'],
      content: m.content,
      streaming: false,
      timestamp: timeStr,
      createdAt: createdAt ?? d.toISOString(),
    };
  }, []);

  const loadSessionMessages = useCallback(async (sessionId: string) => {
    abortRef.current?.abort();
    abortRef.current = null;

    activeSessionIdRef.current = sessionId;
    firstMsgSentRef.current = false;
    setMessages([]);
    setIsLoadingSession(true);
    messagesCursorRef.current = undefined;
    setHasMoreMessages(false);

    const gen = ++fetchGenRef.current;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}/messages`);
      if (res.ok) {
        const data = await res.json();
        const mappedMessages = (data.messages || []).map((m: any, idx: number) => mapDbMessage(m, sessionId, idx));
        if (gen !== fetchGenRef.current) return;
        setMessages(mappedMessages.length > 0 ? mappedMessages : []);
        setIsLoadingSession(false);
        if (mappedMessages.length > 0) {
          firstMsgSentRef.current = true;
          const dbIds = data.messages.map((m: any) => m.id).filter((id: any) => typeof id === 'number');
          messagesCursorRef.current = dbIds.length > 0 ? Math.min(...dbIds) : undefined;
          setHasMoreMessages(data.total !== undefined ? mappedMessages.length < data.total : dbIds.length > 0);
        } else {
          setHasMoreMessages(false);
        }
      } else {
        setIsLoadingSession(false);
      }
    } catch (e) {
      if (gen !== fetchGenRef.current) return;
      setIsLoadingSession(false);
      console.error('Error loading session messages:', e);
    }
    return [];
  }, [mapDbMessage]);

  const loadMoreMessages = useCallback(async (sessionId: string): Promise<number> => {
    const beforeId = messagesCursorRef.current;
    if (beforeId === undefined) return 0;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}/messages?limit=50&before_id=${beforeId}`);
      if (res.ok) {
        const data = await res.json();
        const dbIds = data.messages.map((m: any) => m.id).filter((id: any) => typeof id === 'number');
        const more = (data.messages || []).map((m: any, idx: number) => mapDbMessage(m, sessionId, idx));
        const total = data.total as number | undefined;
        setMessages(prev => {
          const combined = [...more, ...prev];
          setHasMoreMessages(total != null ? combined.length < total : more.length >= 50);
          return combined;
        });
        messagesCursorRef.current = dbIds.length > 0 ? Math.min(...dbIds) : undefined;
        return more.length;
      }
    } catch (e) {
      console.error('Error loading more messages:', e);
    }
    return 0;
  }, [mapDbMessage]);

  const clearChat = useCallback(async (activeSessionId: string) => {
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    try {
      if (limitedMode) {
        clearLocalMemory();
      } else {
        await authFetch('/api/clear' + (activeSessionId ? `?session_id=${activeSessionId}` : ''), { method: 'POST' });
      }
      setMessages([{
        id: Date.now().toString(),
        role: 'assistant',
        content: limitedMode
          ? 'Local demo memory cleared.\nAsk anything when ready.'
          : 'Session cleared, sir.\nAsk anything when ready.',
        streaming: false,
        timestamp: timeStr,
        createdAt: now.toISOString(),
      }]);
      setPhases([]);
      firstMsgSentRef.current = false;
      onStatusChange('Online', false);
    } catch {
      onStatusChange('Clear failed', false);
    }
  }, [limitedMode, onStatusChange]);

  const sendMessage = useCallback(async (
    text: string,
    isVoiceMode: boolean,
    currentSessionId: string,
    renameSession: (id: string, title: string) => void,
  ) => {
    if (!text.trim()) return;

    abortRef.current?.abort();

    const abortController = new AbortController();
    abortRef.current = abortController;

    const streamTimeout = setTimeout(() => abortController.abort(), 120_000);

    const userMsgId = `u-${Date.now()}`;
    const aiMsgId = `a-${Date.now()}`;
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    const createdAt = now.toISOString();

    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user', content: text, streaming: false, timestamp: timeStr, createdAt },
      { id: aiMsgId, role: 'assistant', content: '', streaming: true, timestamp: timeStr, createdAt },
    ]);

    setPhases([]);
    setIsBusy(true);
    onStatusChange('Neural pipeline…', true);

    // Auto-rename after first message
    if (!firstMsgSentRef.current && currentSessionId) {
      firstMsgSentRef.current = true;
      const title = text.trim().slice(0, 42).replace(/\s+/g, ' ') + (text.trim().length > 42 ? '…' : '');
      renameSession(currentSessionId, title);
    }

    let attempt = 0;
    const maxRetries = 3;
    let success = false;

    while (attempt < maxRetries && !success) {
      try {
        if (attempt > 0) {
          onStatusChange(`Reconnecting (Attempt ${attempt}/${maxRetries - 1})…`, true);
          await new Promise(resolve => setTimeout(resolve, Math.pow(2, attempt) * 1000));
        }

        const endpoint = limitedMode ? '/api/chat/limited/stream' : '/api/chat/stream';
        const payload = limitedMode
          ? { message: text, local_context: retrieveLocalMemory(text) }
          : { message: text, voice_mode: isVoiceMode, session_id: currentSessionId };

        const res = await authFetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: abortController.signal,
        });

        if (!res.ok) throw new Error((await res.text()) || res.statusText);

        const reader = res.body?.getReader();
        const decoder = new TextDecoder();
        if (!reader) throw new Error('No readable stream');

        let buffer = '';
        let fullText = '';
        let sawToken = false;
        let streamDone = false;
        let ttsSentence = '';

        let planSteps: { title: string; detail: string; done: boolean }[] = [];
        let planMsgId: string | null = null;

        const streamGen = fetchGenRef.current;

        outer: while (!streamDone) {
          if (streamGen !== fetchGenRef.current) break outer;
          if (abortController.signal.aborted) {
            throw new Error('Stream timed out (120s)');
          }
          const { done, value } = await reader.read();
          if (done) {
            streamDone = true;
            success = true;
            const finalText = fullText;
            setMessages(prev =>
              prev.map(m => m.id === aiMsgId ? { ...m, streaming: false, content: finalText } : m)
            );
            if (planMsgId) {
              const finalSteps = planSteps.map(s => ({ ...s, done: true }));
              setMessages(prev =>
                prev.map(m => m.id === planMsgId
                  ? { ...m, planDone: true, planSteps: finalSteps } as any
                  : m)
              );
            }
            if (finalText.trim() && !limitedMode) {
              const leftover = ttsSentence.trim();
              if (leftover && isSpeakable(leftover)) queueTTS(leftover);
            }
            break outer;
          }

          buffer += decoder.decode(value, { stream: true });

          let idx: number;
          while ((idx = buffer.indexOf('\n\n')) >= 0) {
            const raw = buffer.slice(0, idx).trim();
            buffer = buffer.slice(idx + 2);
            if (!raw.startsWith('data:')) continue;

            const data = raw.slice(5).trim();

            if (data === '[DONE]') {
              streamDone = true;
              success = true;
              const finalText = fullText;
              setMessages(prev =>
                prev.map(m => m.id === aiMsgId ? { ...m, streaming: false, content: finalText } : m)
              );
              if (planMsgId) {
                const finalSteps = planSteps.map(s => ({ ...s, done: true }));
                setMessages(prev =>
                  prev.map(m => m.id === planMsgId
                    ? { ...m, planDone: true, planSteps: finalSteps } as any
                    : m)
                );
              }
              if (finalText.trim()) {
                if (limitedMode) {
                  saveLocalMemory(text, finalText);
                } else {
                  const leftover = ttsSentence.trim();
                  if (leftover && isSpeakable(leftover)) queueTTS(leftover);
                }
              }
              break outer;
            }

            let obj: any;
            try { obj = JSON.parse(data); }
            catch { continue; }

            if (obj.type === 'error') throw new Error(obj.message || 'Stream error');

            if (obj.type === 'phase') {
              const phase = obj as Phase;

              if (phase.id && (phase.id.startsWith('plan_step') || phase.id === 'planner')) {
                if (phase.id === 'planner') {
                  planMsgId = `plan-${Date.now()}`;
                  planSteps = [];
                  setMessages(prev => {
                    const planMsg = {
                      id: planMsgId!,
                      role: 'plan' as any,
                      content: phase.detail || '',
                      streaming: false,
                      timestamp: timeStr,
                      planSteps: [],
                      planDone: false,
                    } as any;
                    const withoutAI = prev.filter(m => m.id !== aiMsgId);
                    return [...withoutAI, planMsg, prev.find(m => m.id === aiMsgId)!];
                  });
                } else {
                  const stepTitle = phase.title || '';
                  const stepDetail = phase.detail || '';
                  planSteps = planSteps.map(s => ({ ...s, done: true }));
                  planSteps = [...planSteps, { title: stepTitle, detail: stepDetail, done: false }];
                  if (planMsgId) {
                    const stepsSnapshot = [...planSteps];
                    setMessages(prev =>
                      prev.map(m => m.id === planMsgId
                        ? { ...m, planSteps: stepsSnapshot } as any
                        : m)
                    );
                  }
                }
                onStatusChange(phase.title || 'Planning…', true);
              } else {
                setPhases(p => [...p, phase]);
                onStatusChange(phase.title || 'Working…', true);
              }
            }

            if (obj.type === 'token' && obj.text) {
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
              ttsSentence += chunk;
              setMessages(prev =>
                prev.map(m => m.id === aiMsgId ? { ...m, content: m.content + chunk } : m)
              );

              if (!limitedMode) {
                const sentBoundary = ttsSentence.match(/^([\s\S]+?[.!?\n])(\s|$)/);
                if (sentBoundary && ttsSentence.length >= 20) {
                  const sentenceToSpeak = sentBoundary[1].trim();
                  ttsSentence = ttsSentence.slice(sentBoundary[0].length);
                  if (sentenceToSpeak.length >= 3 && isSpeakable(sentenceToSpeak)) {
                    queueTTS(sentenceToSpeak);
                  }
                }
              }
            }
          }
        }

        setPhases(p => [...p, {
          id: 'commit',
          title: 'Lattice sealed',
          detail: 'Response materialized · dialogue core synchronized',
        }]);

        success = true;
      } catch (err: any) {
        attempt++;
        console.warn(`Connection attempt ${attempt} failed:`, err);
        if (attempt >= maxRetries) {
          const msg = err?.message ?? String(err);
          setMessages(prev =>
            prev.map(m => m.id === aiMsgId ? { ...m, content: `Connection permanently failed: ${msg}`, streaming: false } : m)
          );
          setPhases(p => [...p, { id: 'fault', title: 'Subsystem fault', detail: msg }]);
        }
      } finally {
        clearTimeout(streamTimeout);
        if (abortRef.current === abortController) {
          abortRef.current = null;
        }
      }
    }

    setIsBusy(false);
    onStatusChange('Online', false);
  }, [limitedMode, onStatusChange, queueTTS]);

  const fetchGreeting = useCallback(async () => {
    const greetingId = `greeting-${Date.now()}`;
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

    setMessages([{
      id: greetingId,
      role: 'assistant',
      content: '',
      streaming: true,
      timestamp: timeStr,
      createdAt: now.toISOString(),
      isGreeting: true,
    } as any]);

    try {
      const res = await authFetch('/api/greeting');
      if (!res.ok || !res.body) throw new Error('Greeting unavailable');

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullText = '';
      let suggestionsData: string[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let idx: number;
        while ((idx = buffer.indexOf('\n\n')) >= 0) {
          const raw = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 2);
          if (!raw.startsWith('data:')) continue;
          const data = raw.slice(5).trim();
          if (data === '[DONE]') break;

          let obj: any;
          try { obj = JSON.parse(data); } catch { continue; }

          if (obj.type === 'token' && obj.text) {
            fullText += obj.text;
            setMessages(prev =>
              prev.map(m => m.id === greetingId ? { ...m, content: fullText } : m)
            );
          }
          if (obj.type === 'suggestions') {
            suggestionsData = obj.suggestions || [];
          }
        }
      }

      setMessages(prev =>
        prev.map(m => m.id === greetingId
          ? { ...m, streaming: false, content: fullText, suggestions: suggestionsData } as any
          : m)
      );
    } catch {
      setMessages([{
        id: greetingId,
        role: 'assistant',
        content: "Systems nominal, sir. What are we working on today?",
        streaming: false,
        timestamp: timeStr,
        createdAt: now.toISOString(),
        isGreeting: true,
        suggestions: ['What is the weather today?', 'Search the web for latest AI news', 'Give me a daily briefing'],
      } as any]);
    }
  }, []);

  const unlinkFile = useCallback(async (filename: string, activeSessionId: string, onDone: (f: string) => void) => {
    if (limitedMode) return;
    try {
      const res = await authFetch(`/api/sessions/${activeSessionId}/files/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        onDone(filename);
      }
    } catch (e) {
      console.error('Error unlinking file:', e);
    }
  }, [limitedMode]);

  return {
    messages,
    setMessages,
    phases,
    setPhases,
    isBusy,
    hasMoreMessages,
    isLoadingSession,
    setIsLoadingSession,
    addSystemMessage,
    sendMessage,
    clearChat,
    loadSessionMessages,
    loadMoreMessages,
    fetchGreeting,
    unlinkFile,
    firstMsgSentRef,
    activeSessionIdRef,
  };
}