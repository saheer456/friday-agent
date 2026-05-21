import { useState, useCallback, useEffect } from 'react';
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

  // Session states
  const [sessions, setSessions] = useState<{ id: string; title: string; created_at?: string }[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('default-session');
  const [activeSessionFiles, setActiveSessionFiles] = useState<string[]>([]);

  const addSystemMessage = useCallback((text: string) => {
    setMessages(prev => [...prev, { id: Date.now().toString(), role: 'assistant', content: text, streaming: false }]);
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
    if (limitedMode) return;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}/messages`);
      if (res.ok) {
        const data = await res.json();
        const mappedMessages = (data.messages || []).map((m: any, idx: number) => ({
          id: `m-${sessionId}-${idx}`,
          role: m.role,
          content: m.content,
          streaming: false,
        }));
        setMessages(mappedMessages.length > 0 ? mappedMessages : [{
          id: `m-${sessionId}-welcome`,
          role: 'assistant',
          content: 'Session connected, sir. Ask anything when ready.',
          streaming: false,
        }]);
        setActiveSessionFiles(data.files || []);
      }
    } catch (e) {
      console.error('Error loading session messages:', e);
    }
  }, [limitedMode]);

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
        await selectSession(newId);
      }
    } catch (e) {
      console.error('Error creating session:', e);
    }
  }, [limitedMode, fetchSessions, selectSession]);

  const deleteSession = useCallback(async (sessionId: string) => {
    if (limitedMode) return;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (res.ok) {
        const remaining = sessions.filter(s => s.id !== sessionId);
        setSessions(remaining);
        
        const nextSessionId = remaining.length > 0 ? remaining[0].id : 'default-session';
        await selectSession(nextSessionId);
        await fetchSessions();
      }
    } catch (e) {
      console.error('Error deleting session:', e);
    }
  }, [limitedMode, sessions, fetchSessions, selectSession]);

  const renameSession = useCallback(async (sessionId: string, newTitle: string) => {
    if (limitedMode) return;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle }),
      });
      if (res.ok) {
        await fetchSessions();
        // Update local session title if it's the active one or just to reflect change in real time
        setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title: newTitle } : s));
      }
    } catch (e) {
      console.error('Error renaming session:', e);
    }
  }, [limitedMode, fetchSessions]);

  const clearChat = useCallback(async () => {
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
      }]);
      setPhases([]);
      setActiveSessionFiles([]);
      onStatusChange('Online', false);
    } catch {
      onStatusChange('Clear failed', false);
    }
  }, [limitedMode, activeSessionId, onStatusChange]);

  // Fetch sessions list and select default session on mount
  useEffect(() => {
    if (!limitedMode) {
      fetchSessions().then(() => {
        selectSession('default-session');
      });
    }
  }, [limitedMode]);

  const sendMessage = useCallback(async (text: string, isVoiceMode: boolean) => {
    if (!text.trim()) return;

    const userMsgId = `u-${Date.now()}`;
    const aiMsgId   = `a-${Date.now()}`;

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
        : { message: text, voice_mode: isVoiceMode, session_id: activeSessionId };
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

          if (data === '[DONE]') {
            streamDone = true;
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

          let obj: any;
          try { obj = JSON.parse(data); }
          catch { continue; }

          if (obj.type === 'error') throw new Error(obj.message || 'Stream error');

          if (obj.type === 'phase') {
            setPhases(p => [...p, obj as Phase]);
            onStatusChange(obj.title || 'Working…', true);
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
  }, [limitedMode, activeSessionId, onStatusChange, queueTTS]);

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
    setActiveSessionFiles
  };
}

