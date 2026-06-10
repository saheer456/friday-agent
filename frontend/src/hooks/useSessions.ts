import { useState, useCallback, useEffect, useRef } from 'react';
import { authFetch } from '../lib/api';
import { supabase } from '../lib/supabase';

export interface Session {
  id: string;
  title: string;
  created_at?: string;
  updated_at?: string;
  message_count?: number;
}

export function useSessions(limitedMode: boolean) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>('');
  const [activeSessionFiles, setActiveSessionFiles] = useState<string[]>([]);
  const searchQueryRef = useRef('');

  const sortSessions = useCallback((list: Session[]) => {
    return [...list].sort((a, b) =>
      (b.updated_at || b.created_at || '').localeCompare(a.updated_at || a.created_at || ''),
    );
  }, []);

  const fetchSessions = useCallback(async (searchQuery?: string): Promise<Session[]> => {
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
        setSessions(prev => sortSessions([
          { id: serverId, title: sessionTitle, created_at: now, updated_at: now, message_count: 0 },
          ...prev.filter(s => s.id !== serverId),
        ]));
        setActiveSessionId(serverId);
        setActiveSessionFiles([]);
        return serverId;
      }
    } catch (e) {
      console.error('Error creating session:', e);
    }
    return null;
  }, [limitedMode, sortSessions]);

  const deleteSession = useCallback(async (sessionId: string) => {
    if (limitedMode) return null;
    try {
      const res = await authFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (res.ok) {
        let nextId: string | null = null;
        setSessions(prev => {
          const remaining = prev.filter(s => s.id !== sessionId);
          if (remaining.length > 0) nextId = remaining[0].id;
          return remaining;
        });
        return nextId;
      }
    } catch (e) {
      console.error('Error deleting session:', e);
    }
    return null;
  }, [limitedMode]);

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

  // Supabase Realtime subscription
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

  return {
    sessions,
    activeSessionId,
    activeSessionFiles,
    setActiveSessionId,
    setActiveSessionFiles,
    fetchSessions,
    createSession,
    deleteSession,
    renameSession,
    searchQueryRef,
  };
}