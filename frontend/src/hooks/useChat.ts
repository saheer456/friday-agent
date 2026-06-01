import { useState, useCallback, useEffect, useRef } from 'react';
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

  const [reconnectCount, setReconnectCount] = useState(0);
  const [isReconnecting, setIsReconnecting] = useState(false);

  const [sessions, setSessions] = useState<{ id: string; title: string; created_at?: string }[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [activeSessionFiles, setActiveSessionFiles] = useState<string[]>([]);

  // Track whether the first user message has been sent (for auto-rename)
  const firstMsgSentRef = useRef(false);
  const activeSessionIdRef = useRef(activeSessionId);
  useEffect(() => { activeSessionIdRef.current = activeSessionId; }, [activeSessionId]);

  const addSystemMessage = useCallback((text: string) => {
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    setMessages(prev => [...prev, { id: Date.now().toString(), role: 'assistant', content: text, streaming: false, timestamp: timeStr }]);
  }, []);

  const fetchSessions = useCallback(async () => {
    if (limitedMode) return;
    try {
      const res = await authFetch('/api/sessions');
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch (e) {
      console.error('Error fetching sessions:', e);
    }
  }, [limitedMode]);

  const selectSession = useCallback(async (sessionId: string) => {
    setActiveSessionId(sessionId);
    firstMsgSentRef.current = false;
    if (limitedMode) return;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}/messages`);
      if (res.ok) {
        const data = await res.json();
        const mappedMessages = (data.messages || []).map((m: any, idx: number) => {
          let timeStr = '';
          if (m.created_at) {
            try {
              const dateStr = m.created_at.includes(' ') && !m.created_at.includes('T') && !m.created_at.includes('Z')
                ? m.created_at.replace(' ', 'T') + 'Z'
                : m.created_at;
              const d = new Date(dateStr);
              if (!isNaN(d.getTime())) {
                timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
              }
            } catch (e) {
              console.error('Error parsing created_at:', e);
            }
          }
          if (!timeStr) {
            timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
          }
          return {
            id: `m-${sessionId}-${idx}`,
            role: m.role,
            content: m.content,
            streaming: false,
            timestamp: timeStr,
          };
        });
        setMessages(mappedMessages.length > 0 ? mappedMessages : []);
        setActiveSessionFiles(data.files || []);
        if (mappedMessages.length > 0) {
          firstMsgSentRef.current = true;
        }
      }
    } catch (e) {
      console.error('Error loading session messages:', e);
    }
  }, [limitedMode]);

  // ── Personalized streaming greeting ──────────────────────────
  const fetchGreeting = useCallback(async () => {
    const greetingId = `greeting-${Date.now()}`;
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

    // Insert a streaming bubble immediately
    setMessages([{
      id: greetingId,
      role: 'assistant',
      content: '',
      streaming: true,
      timestamp: timeStr,
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

      // Mark streaming complete, attach suggestions
      setMessages(prev =>
        prev.map(m => m.id === greetingId
          ? { ...m, streaming: false, content: fullText, suggestions: suggestionsData } as any
          : m)
      );
    } catch {
      // Fallback to a warm static greeting
      setMessages([{
        id: greetingId,
        role: 'assistant',
        content: "Systems nominal, sir. What are we working on today?",
        streaming: false,
        timestamp: timeStr,
        isGreeting: true,
        suggestions: ['What is the weather today?', 'Search the web for latest AI news', 'Give me a daily briefing'],
      } as any]);
    }
  }, []);

  const createSession = useCallback(async (title?: string) => {
    if (limitedMode) return;
    const newId = `session-${Date.now()}`;
    try {
      const res = await authFetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: newId, title: title || 'New Chat' }),
      });
      if (res.ok) {
        await fetchSessions();
        setActiveSessionId(newId);
        firstMsgSentRef.current = false;
        setMessages([]);
        setActiveSessionFiles([]);
        // Fetch personalized greeting for the fresh session
        await fetchGreeting();
      }
    } catch (e) {
      console.error('Error creating session:', e);
    }
  }, [limitedMode, fetchSessions, fetchGreeting]);

  const deleteSession = useCallback(async (sessionId: string) => {
    if (limitedMode) return;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (res.ok) {
        const remaining = sessions.filter(s => s.id !== sessionId);
        setSessions(remaining);
        if (remaining.length > 0) {
          await selectSession(remaining[0].id);
        } else {
          await createSession();
        }
        await fetchSessions();
      }
    } catch (e) {
      console.error('Error deleting session:', e);
    }
  }, [limitedMode, sessions, fetchSessions, selectSession, createSession]);

  const renameSession = useCallback(async (sessionId: string, newTitle: string) => {
    if (limitedMode) return;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle }),
      });
      if (res.ok) {
        setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title: newTitle } : s));
      }
    } catch (e) {
      console.error('Error renaming session:', e);
    }
  }, [limitedMode]);

  const clearChat = useCallback(async () => {
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
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
      }]);
      setPhases([]);
      setActiveSessionFiles([]);
      firstMsgSentRef.current = false;
      onStatusChange('Online', false);
    } catch {
      onStatusChange('Clear failed', false);
    }
  }, [limitedMode, activeSessionId, onStatusChange]);

  // On mount: create a fresh session (never reuse default-session)
  useEffect(() => {
    if (!limitedMode) {
      fetchSessions().then(() => {
        createSession();
      });
    }
  }, [limitedMode]); // eslint-disable-line react-hooks/exhaustive-deps

  const sendMessage = useCallback(async (text: string, isVoiceMode: boolean) => {
    if (!text.trim()) return;

    const userMsgId = `u-${Date.now()}`;
    const aiMsgId   = `a-${Date.now()}`;
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user',      content: text, streaming: false, timestamp: timeStr },
      { id: aiMsgId,   role: 'assistant', content: '',   streaming: true,  timestamp: timeStr },
    ]);

    setPhases([]);
    setIsBusy(true);
    onStatusChange('Neural pipeline…', true);

    // Auto-rename session after first user message
    const currentSessionId = activeSessionIdRef.current;
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
          setIsReconnecting(true);
          setReconnectCount(attempt);
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
        });

        if (!res.ok) throw new Error((await res.text()) || res.statusText);

        const reader  = res.body?.getReader();
        const decoder = new TextDecoder();
        if (!reader) throw new Error('No readable stream');

        let buffer    = '';
        let fullText  = '';
        let sawToken  = false;
        let streamDone = false;
        let ttsSentence = '';  // accumulates until sentence boundary

        // Plan steps collector
        let planSteps: { title: string; detail: string; done: boolean }[] = [];
        let planMsgId: string | null = null;

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

            if (data === '[DONE]') {
              streamDone = true;
              success = true;
              const finalText = fullText;
              setMessages(prev =>
                prev.map(m => m.id === aiMsgId ? { ...m, streaming: false, content: finalText } : m)
              );
              // Mark plan as complete
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
                  // Send any leftover sentence buffer not yet spoken
                  const leftover = ttsSentence.trim();
                  if (leftover) queueTTS(leftover);
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

              // Planner steps → inject inline PlanCard into chat
              if (phase.id && (phase.id.startsWith('plan_step') || phase.id === 'planner')) {
                if (phase.id === 'planner') {
                  // Create the plan card message
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
                    // Insert before the streaming AI bubble
                    const withoutAI = prev.filter(m => m.id !== aiMsgId);
                    return [...withoutAI, planMsg, prev.find(m => m.id === aiMsgId)!];
                  });
                } else {
                  // Add step to existing plan card
                  const stepTitle = phase.title || '';
                  const stepDetail = phase.detail || '';
                  // Mark previous steps as done
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
                // Also show in status bar
                onStatusChange(phase.title || 'Planning…', true);
              } else {
                // Non-planner phases go to telemetry panel
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

              // Streaming TTS: fire at sentence boundary
              if (!limitedMode) {
                const sentBoundary = ttsSentence.match(/^([\s\S]+?[.!?\n])(\s|$)/);
                if (sentBoundary && ttsSentence.length >= 20) {
                  const sentenceToSpeak = sentBoundary[1].trim();
                  ttsSentence = ttsSentence.slice(sentBoundary[0].length);
                  queueTTS(sentenceToSpeak);
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
            prev.map(m => m.id === aiMsgId ? { ...m, content: `⚠️ Connection permanently failed: ${msg}`, streaming: false } : m)
          );
          setPhases(p => [...p, { id: 'fault', title: 'Subsystem fault', detail: msg }]);
        }
      } finally {
        setIsReconnecting(false);
        setReconnectCount(0);
      }
    }

    setIsBusy(false);
    onStatusChange('Online', false);
  }, [limitedMode, onStatusChange, queueTTS, renameSession]);

  const unlinkFile = useCallback(async (filename: string) => {
    if (limitedMode) return;
    try {
      const res = await authFetch(`/api/sessions/${activeSessionId}/files/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setActiveSessionFiles(prev => prev.filter(f => f !== filename));
      }
    } catch (e) {
      console.error('Error unlinking file:', e);
    }
  }, [limitedMode, activeSessionId]);

  return {
    messages,
    phases,
    isBusy,
    sendMessage,
    clearChat,
    addSystemMessage,
    sessions,
    activeSessionId,
    activeSessionFiles,
    fetchSessions,
    selectSession,
    createSession,
    deleteSession,
    renameSession,
    unlinkFile,
    setActiveSessionFiles,
    reconnectCount,
    isReconnecting,
  };
}
