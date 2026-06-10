import { useCallback, useEffect } from 'react';
import { useSessions } from './useSessions';
import { useStreaming } from './useStreaming';

interface UseChatOptions {
  limitedMode?: boolean;
}

export function useChat(
  onStatusChange: (status: string, busy: boolean) => void,
  queueTTS: (text: string) => void,
  options: UseChatOptions = {},
) {
  const { limitedMode = false } = options;

  // Sessions
  const {
    sessions,
    activeSessionId,
    activeSessionFiles,
    setActiveSessionId,
    setActiveSessionFiles,
    fetchSessions,
    createSession: createRawSession,
    deleteSession: deleteRawSession,
    renameSession,
  } = useSessions(limitedMode);

  // Streaming
  const {
    messages,
    phases,
    isBusy,
    hasMoreMessages,
    isLoadingSession,
    setIsLoadingSession,
    addSystemMessage,
    sendMessage: rawSendMessage,
    clearChat: rawClearChat,
    loadSessionMessages,
    loadMoreMessages,
    fetchGreeting,
    unlinkFile: rawUnlinkFile,
    firstMsgSentRef,
    activeSessionIdRef,
  } = useStreaming(onStatusChange, queueTTS, limitedMode);

  // Sync session ID ref
  useEffect(() => { activeSessionIdRef.current = activeSessionId; }, [activeSessionId, activeSessionIdRef]);

  const createSession = useCallback(async (title?: string) => {
    const sid = await createRawSession(title);
    if (sid) {
      setIsLoadingSession(true);
      await fetchGreeting();
      setIsLoadingSession(false);
    }
  }, [createRawSession, fetchGreeting, setIsLoadingSession]);

  const deleteSession = useCallback(async (sessionId: string) => {
    const nextId = await deleteRawSession(sessionId);
    if (nextId) {
      setActiveSessionId(nextId);
      await loadSessionMessages(nextId);
    } else {
      await createSession();
    }
  }, [deleteRawSession, setActiveSessionId, loadSessionMessages, createSession]);

  const selectSession = useCallback(async (sessionId: string) => {
    setActiveSessionId(sessionId);
    firstMsgSentRef.current = false;
    setIsLoadingSession(true);
    await loadSessionMessages(sessionId);
    setActiveSessionFiles([]);
  }, [setActiveSessionId, loadSessionMessages, setActiveSessionFiles, setIsLoadingSession, firstMsgSentRef]);

  const clearChat = useCallback(async () => {
    await rawClearChat(activeSessionId);
  }, [rawClearChat, activeSessionId]);

  const sendMessage = useCallback(async (text: string, isVoiceMode: boolean) => {
    await rawSendMessage(text, isVoiceMode, activeSessionId, renameSession);
  }, [rawSendMessage, activeSessionId, renameSession]);

  const unlinkFile = useCallback(async (filename: string) => {
    await rawUnlinkFile(filename, activeSessionId, (f: string) => {
      setActiveSessionFiles(prev => prev.filter(x => x !== f));
    });
  }, [rawUnlinkFile, activeSessionId, setActiveSessionFiles]);

  // On mount: always create a fresh session
  useEffect(() => {
    if (!limitedMode) {
      createSession();
    }
  }, [limitedMode]); // eslint-disable-line react-hooks/exhaustive-deps

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
    isLoadingSession,
    loadMoreMessages,
    hasMoreMessages,
  };
}