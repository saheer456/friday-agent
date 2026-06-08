import { useState, useCallback, useEffect, useRef } from 'react';
import type { Message, Phase } from '../types/api';
import { authFetch } from '../lib/api';
import { clearLocalMemory, retrieveLocalMemory, saveLocalMemory } from '../lib/localMemory';
import { supabase } from '../lib/supabase';

interface UseChatOptions {
  limitedMode?: boolean;
}

function parseCreatedAt(raw?: string): string | undefined {
  if (!raw) return undefined;
  const normalized = raw.includes(' ') && !raw.includes('T') && !raw.includes('Z')
    ? raw.replace(' ', 'T') + 'Z'
    : raw;
  const d = new Date(normalized);
  return isNaN(d.getTime()) ? undefined : d.toISOString();
}

function isSpeakable(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;

  // Skip code fences
  if (trimmed.startsWith('```') || trimmed.endsWith('```')) return false;

  // Skip lines that look like markdown table rows/dividers
  if (trimmed.includes('|') && (trimmed.includes('---') || trimmed.includes('-|-'))) return false;

  // Skip JSON blocks or chunks that look like JSON objects/arrays
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) return false;
  if (/["'][a-zA-Z0-9_-]+["']\s*:/i.test(trimmed)) return false; // JSON key-value

  // Skip common coding declarations
  if (/^(import|const|let|var|function|class|def|return|from|public|private|async|await)\s/i.test(trimmed)) return false;

  // Skip common Mermaid syntax
  if (/^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph)\b/i.test(trimmed)) return false;
  if (trimmed.includes('-->') || trimmed.includes('---') || trimmed.includes('==>')) return false;

  // Calculate letters/numbers ratio to filter out symbol-heavy text (code/data/config)
  const letters = trimmed.replace(/[^a-zA-Z0-9]/g, '').length;
  if (letters === 0) return false;
  if (trimmed.length > 10 && letters / trimmed.length < 0.4) return false;

  // Filter out short fragments that don't have enough words
  const words = trimmed.split(/\s+/).filter(w => w.length > 0);
  if (words.length < 2) {
    if (!/^[a-zA-Z]{2,15}$/.test(trimmed)) return false;
  }

  return true;
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
  const [isLoadingSession, setIsLoadingSession] = useState(false);

  const [sessions, setSessions] = useState<{ id: string; title: string; created_at?: string; updated_at?: string; message_count?: number }[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [activeSessionFiles, setActiveSessionFiles] = useState<string[]>([]);

  // Track whether the first user message has been sent (for auto-rename)
  const firstMsgSentRef = useRef(false);
  const activeSessionIdRef = useRef(activeSessionId);
  useEffect(() => { activeSessionIdRef.current = activeSessionId; }, [activeSessionId]);

  // Abort controller for in-flight stream — cancelled on session switch
  const abortRef = useRef<AbortController | null>(null);

  // Generation counter for stale-response guarding
  const fetchGenRef = useRef(0);

  // Cursor for loading older messages
  const messagesCursorRef = useRef<number | undefined>(undefined);
  const [hasMoreMessages, setHasMoreMessages] = useState(false);

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

  const sortSessions = useCallback((list: { id: string; title: string; created_at?: string; updated_at?: string; message_count?: number }[]) => {
    return [...list].sort((a, b) =>
      (b.updated_at || b.created_at || '').localeCompare(a.updated_at || a.created_at || ''),
    );
  }, []);

  const searchQueryRef = useRef('');
  const fetchSessions = useCallback(async (searchQuery?: string): Promise<{ id: string; title: string; created_at?: string; updated_at?: string; message_count?: number }[]> => {
    searchQueryRef.current = searchQuery || '';
    if (limitedMode) return [];
    try {
      const params = searchQuery ? `?search=${encodeURIComponent(searchQuery)}` : '';
      const res = await authFetch(`/api/sessions${params}`);
      if (res.ok) {
        const data = await res.json();
        const list = sortSessions(data.sessions || []);
        setSessions(list);
        return list;
      }
      console.error('fetchSessions failed:', res.status, await res.text());
    } catch (e) {
      console.error('Error fetching sessions:', e);
    }
    return [];
  }, [limitedMode, sortSessions]);

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

  const selectSession = useCallback(async (sessionId: string) => {
    // Cancel any in-flight stream
    abortRef.current?.abort();
    abortRef.current = null;

    setActiveSessionId(sessionId);
    firstMsgSentRef.current = false;
    if (limitedMode) return;

    setMessages([]);
    setActiveSessionFiles([]);
    setIsLoadingSession(true);
    messagesCursorRef.current = undefined;
    setHasMoreMessages(false);

    const gen = ++fetchGenRef.current;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}/messages`);
      if (res.ok) {
        const data = await res.json();
        const mappedMessages = (data.messages || []).map((m: any, idx: number) => mapDbMessage(m, sessionId, idx));
        if (gen !== fetchGenRef.current) return; // stale response
        setMessages(mappedMessages.length > 0 ? mappedMessages : []);
        setActiveSessionFiles(data.files || []);
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
  }, [limitedMode, mapDbMessage]);

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

  // ── Personalized streaming greeting ──────────────────────────
  const fetchGreeting = useCallback(async () => {
    const greetingId = `greeting-${Date.now()}`;
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

    // Insert a streaming bubble immediately
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
        createdAt: now.toISOString(),
        isGreeting: true,
        suggestions: ['What is the weather today?', 'Search the web for latest AI news', 'Give me a daily briefing'],
      } as any]);
    }
  }, []);

  // ── Supabase Realtime subscription ─────────────────────────
  useEffect(() => {
    if (!supabase || limitedMode || searchQueryRef.current) return;

    let channel: ReturnType<typeof supabase.channel> | null = null;
    let cancelled = false;

    (async () => {
      const { data: { user } } = await supabase!.auth.getUser();
      if (!user || cancelled) return;

      channel = supabase!
        .channel('sessions-realtime')
        .on('postgres_changes',
          { event: '*', schema: 'public', table: 'sessions', filter: `user_id=eq.${user.id}` },
          (payload) => {
            if (cancelled || searchQueryRef.current) return;
            const { eventType, new: row } = payload;

            if (eventType === 'INSERT') {
              setSessions(prev => sortSessions(
                prev.some(s => s.id === row.id)
                  ? prev
                  : [{ id: row.id, title: row.title, created_at: row.created_at, updated_at: row.updated_at, message_count: row.message_count }, ...prev],
              ));
            } else if (eventType === 'UPDATE') {
              setSessions(prev => sortSessions(
                prev.map(s => s.id === row.id
                  ? { ...s, title: row.title, updated_at: row.updated_at, message_count: row.message_count }
                  : s),
              ));
            } else if (eventType === 'DELETE') {
              setSessions(prev => prev.filter(s => s.id !== payload.old.id));
            }
          },
        )
        .subscribe();
    })();

    return () => {
      cancelled = true;
      if (channel) supabase!.removeChannel(channel);
    };
  }, [limitedMode, sortSessions]);

  const createSession = useCallback(async (title?: string) => {
    if (limitedMode) return;
    const sessionTitle = title || 'New Chat';
    try {
      const res = await authFetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: sessionTitle }),
      });
      if (res.ok) {
        const data = await res.json();
        const serverId = data.id as string;
        const now = new Date().toISOString();
        // Optimistic update so the sidebar shows the new chat immediately
        setSessions(prev => sortSessions([
          { id: serverId, title: sessionTitle, created_at: now, updated_at: now, message_count: 0 },
          ...prev.filter(s => s.id !== serverId),
        ]));
        setActiveSessionId(serverId);
        firstMsgSentRef.current = false;
        setMessages([]);
        setActiveSessionFiles([]);
        setHasMoreMessages(false);
        messagesCursorRef.current = undefined;
        await fetchSessions();
        await fetchGreeting();
      } else {
        console.error('createSession failed:', res.status, await res.text());
      }
    } catch (e) {
      console.error('Error creating session:', e);
    }
  }, [limitedMode, fetchSessions, fetchGreeting, sortSessions]);

  const deleteSession = useCallback(async (sessionId: string) => {
    if (limitedMode) return;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (res.ok) {
        // Use functional update to avoid stale closure
        let nextId: string | null = null;
        setSessions(prev => {
          const remaining = prev.filter(s => s.id !== sessionId);
          if (remaining.length > 0) {
            nextId = remaining[0].id;
          }
          return remaining;
        });
        if (nextId) {
          await selectSession(nextId);
        } else {
          await createSession();
        }
      }
    } catch (e) {
      console.error('Error deleting session:', e);
    }
  }, [limitedMode, selectSession, createSession]);

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
      setActiveSessionFiles([]);
      firstMsgSentRef.current = false;
      onStatusChange('Online', false);
    } catch {
      onStatusChange('Clear failed', false);
    }
  }, [limitedMode, activeSessionId, onStatusChange]);

  // On mount: restore the most recent session, or create one if none exist.
  // Bug fix: previously always called createSession() which discarded all history on every page load.
  useEffect(() => {
    if (!limitedMode) {
      fetchSessions().then((existingSessions) => {
        if (existingSessions.length > 0) {
          // Restore the most recent session (first in DESC-ordered list)
          selectSession(existingSessions[0].id);
        } else {
          // No sessions at all — create the first one
          createSession();
        }
      });
    }
  }, [limitedMode]); // eslint-disable-line react-hooks/exhaustive-deps

  const sendMessage = useCallback(async (text: string, isVoiceMode: boolean) => {
    if (!text.trim()) return;

    // Abort any previous stream
    abortRef.current?.abort();

    const abortController = new AbortController();
    abortRef.current = abortController;

    const userMsgId = `u-${Date.now()}`;
    const aiMsgId   = `a-${Date.now()}`;
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    const createdAt = now.toISOString();

    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user',      content: text, streaming: false, timestamp: timeStr, createdAt },
      { id: aiMsgId,   role: 'assistant', content: '',   streaming: true,  timestamp: timeStr, createdAt },
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
          signal: abortController.signal,
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

        const streamGen = fetchGenRef.current;

        outer: while (!streamDone) {
          if (streamGen !== fetchGenRef.current) break outer; // session switched
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
            prev.map(m => m.id === aiMsgId ? { ...m, content: `⚠️ Connection permanently failed: ${msg}`, streaming: false } : m)
          );
          setPhases(p => [...p, { id: 'fault', title: 'Subsystem fault', detail: msg }]);
        }
      } finally {
        if (abortRef.current === abortController) {
          abortRef.current = null;
        }
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
    isLoadingSession,
    loadMoreMessages,
    hasMoreMessages,
  };
}
