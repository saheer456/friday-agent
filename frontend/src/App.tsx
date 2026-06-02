import { useState, useCallback, useEffect } from 'react';
import { Header } from './components/Header/Header';
import { ChatArea } from './components/ChatArea/ChatArea';
import { Composer } from './components/Composer/Composer';
import { Telemetry } from './components/Telemetry/Telemetry';
import { Memories } from './components/Memories/Memories';
import { Sidebar } from './components/Sidebar/Sidebar';
import { ConfirmModal } from './components/ConfirmModal/ConfirmModal';
import { useSystem } from './hooks/useSystem';
import { useChat } from './hooks/useChat';
import { useVoice } from './hooks/useVoice';
import { useFileUpload } from './hooks/useFileUpload';
import { supabase } from './lib/supabase';
import styles from './App.module.css';

function App() {
  const [statusText, setStatusText] = useState('Online');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [telemetryOpen, setTelemetryOpen] = useState(false);
  const [memoriesOpen, setMemoriesOpen] = useState(false);
  const [interimText, setInterimText] = useState('');
  const [composerValue, setComposerValue] = useState('');
  const [initialComposerValue, setInitialComposerValue] = useState('');
  const [authLoading, setAuthLoading] = useState(true);
  const [loginEnabled, setLoginEnabled] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [hasFullAccess, setHasFullAccess] = useState(false);
  const [authMode, setAuthMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loginError, setLoginError] = useState('');
  const [authNotice, setAuthNotice] = useState('');
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const limitedMode = loginEnabled && isAuthenticated && !hasFullAccess;

  const { system, fetchSystem } = useSystem(!authLoading && (!loginEnabled || isAuthenticated));
  const uploadState = useFileUpload();

  const handleStatusChange = useCallback((status: string, busy: boolean) => {
    setStatusText(status);
    if (!busy) fetchSystem();
  }, [fetchSystem]);

  const { isRecording, isPlaying, toggleRecording, stopAudio, queueTTS, sttSupported } = useVoice(
    (speechText) => {
      setInterimText('');
      const finalMsg = (initialComposerValue.trim() + ' ' + speechText.trim()).trim();
      setComposerValue('');
      setInitialComposerValue('');
      if (finalMsg) {
        handleSend(finalMsg, true);
      }
    },
    (speechText) => {
      setInterimText(speechText);
      setComposerValue((initialComposerValue.trim() + ' ' + speechText.trim()).trim());
    },
  );

  const handleToggleRecord = () => {
    if (!isRecording) {
      setInitialComposerValue(composerValue);
    }
    toggleRecording();
  };

  const {
    messages,
    phases,
    isBusy: chatBusy,
    sendMessage,
    clearChat,
    addSystemMessage,
    sessions,
    activeSessionId,
    activeSessionFiles,
    selectSession,
    createSession,
    deleteSession,
    renameSession,
    unlinkFile,
    setActiveSessionFiles,
  } = useChat(handleStatusChange, hasFullAccess ? queueTTS : () => {}, { limitedMode });

  const handleSend = async (text: string, isVoiceMode: boolean) => {
    if (chatBusy) return;
    stopAudio();
    await sendMessage(text, isVoiceMode);
  };

  const handleUpload = async (file: File) => {
    const data = await uploadState.uploadFile(file, activeSessionId);
    if (data) {
      addSystemMessage(
        `I've ingested **${data.filename}** into the active dialogue channel, sir. ` +
        `It's been split into ${data.chunks} searchable chunks (~${data.words} words total). ` +
        `You can now ask me questions isolated specifically to this session's context.`
      );
      // Update session files directly to avoid resetting the chat transcript
      setActiveSessionFiles(prev => [...prev.filter(f => f !== data.filename), data.filename]);
    }
  };


  const handleLogout = async () => {
    await supabase?.auth.signOut();
    setIsAuthenticated(false);
    setHasFullAccess(false);
    setEmail('');
    setPassword('');
    setTelemetryOpen(false);
    setMemoriesOpen(false);
  };

  const refreshAuth = useCallback(async (tokenOverride?: string | null) => {
    const ctrl = new AbortController();
    const timeout = window.setTimeout(() => ctrl.abort(), 6000);
    try {
      let token: string | null = tokenOverride ?? null;
      if (!token && supabase) {
        const sessionResult = await Promise.race([
          supabase.auth.getSession(),
          new Promise<null>((resolve) => window.setTimeout(() => resolve(null), 2500)),
        ]);
        token = sessionResult && 'data' in sessionResult
          ? sessionResult.data.session?.access_token ?? null
          : null;
      }
      const headers = token ? { Authorization: `Bearer ${token}` } : undefined;
      const res = await fetch('/api/auth/me', { headers, signal: ctrl.signal });
      if (!res.ok) throw new Error('Auth check failed');
      const data = await res.json();
      setLoginEnabled(Boolean(data.login_enabled));
      setIsAuthenticated(Boolean(data.authenticated));
      setHasFullAccess(Boolean(data.full_access));
      return Boolean(data.authenticated);
    } catch {
      setLoginEnabled(true);
      setIsAuthenticated(false);
      setHasFullAccess(false);
      setLoginError('Backend is not reachable. Start the server and refresh.');
      return false;
    } finally {
      window.clearTimeout(timeout);
      setAuthLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshAuth();

    if (!supabase) return;
    const { data: sub } = supabase.auth.onAuthStateChange(async (_event, session) => {
      await refreshAuth(session?.access_token ?? null);
    });
    return () => sub.subscription.unsubscribe();
  }, [refreshAuth]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError('');
    setAuthNotice('');
    if (!supabase) {
      setLoginError('Supabase client is not configured.');
      return;
    }
    const { data, error } = authMode === 'signin'
      ? await supabase.auth.signInWithPassword({ email, password })
      : await supabase.auth.signUp({ email, password });
    if (error) {
      setLoginError(error.message);
      return;
    }
    if (authMode === 'signup') {
      setAuthNotice('Account created. Check your email if confirmation is enabled, then sign in.');
      setAuthMode('signin');
      setPassword('');
      return;
    }
    const ok = await refreshAuth(data.session?.access_token ?? null);
    if (!ok) {
      setLoginError('Signed in, but backend access was not confirmed. Refresh and try again.');
    }
    setPassword('');
  };

  if (authLoading) {
    return (
      <div className={styles.authShell}>
        <div className={styles.authLoadingWrapper}>
          <div className={styles.authLoadingLogo}></div>
          <div className={styles.authLoadingText}>Synchronizing neural cores…</div>
        </div>
      </div>
    );
  }

  if (loginEnabled && !isAuthenticated) {
    return (
      <div className={styles.authShell}>
        <form className={styles.authCard} onSubmit={handleLogin}>
          <h1 className={styles.authTitle}>FRIDAY Access</h1>
          <p className={styles.authText}>
            {authMode === 'signin' ? 'Sign in with your Supabase account.' : 'Create a tester account.'}
          </p>
          <input
            className={styles.authInput}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email"
            autoComplete="email"
            required
          />
          <input
            className={styles.authInput}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete="current-password"
            required
          />
          {loginError ? <p className={styles.authError}>{loginError}</p> : null}
          {authNotice ? <p className={styles.authNotice}>{authNotice}</p> : null}
          <button className={styles.authButton} type="submit">
            {authMode === 'signin' ? 'Sign in' : 'Create account'}
          </button>
          <button
            className={styles.authLinkButton}
            type="button"
            onClick={() => {
              setAuthMode(authMode === 'signin' ? 'signup' : 'signin');
              setLoginError('');
              setAuthNotice('');
            }}
          >
            {authMode === 'signin' ? 'New user? Create an account' : 'Already have an account? Sign in'}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className={styles.layout}>
      <Sidebar
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(o => !o)}
        sessions={sessions}
        activeSessionId={activeSessionId}
        activeSessionFiles={activeSessionFiles}
        onCreateSession={() => createSession()}
        onSelectSession={selectSession}
        onDeleteSession={deleteSession}
        onRenameSession={renameSession}
      />
      <div className={styles.mainCol}>
        <Header
          version={system?.ui?.version || 'v4.0 Nexus'}
          statusText={statusText}
          isBusy={chatBusy}
          isSpeaking={isPlaying}
          onClearChat={() => setShowClearConfirm(true)}
          onToggleTelemetry={() => setTelemetryOpen(o => !o)}
          onToggleMemories={() => setMemoriesOpen(o => !o)}
          onLogout={handleLogout}
          onToggleSidebar={() => setSidebarOpen(o => !o)}
          fullAccess={hasFullAccess}
        />

        {limitedMode && (
          <div className={styles.limitedBanner}>
            Basic demo mode. Weather and browser-local memory are available. Contact khansaheer424@gmail.com for full access.
          </div>
        )}

        <ChatArea
          messages={messages}
          isSpeaking={isPlaying}
          onDropFile={hasFullAccess ? handleUpload : undefined}
          onSelectSuggestion={(text) => setComposerValue(text)}
        />

        <div className={styles.composerWrap}>
          <Composer
            value={composerValue}
            onChange={setComposerValue}
            onSend={handleSend}
            isBusy={chatBusy}
            isRecording={isRecording}
            onToggleRecord={handleToggleRecord}
            onUpload={handleUpload}
            allowUpload={hasFullAccess}
            uploadState={{
              isUploading: uploadState.isUploading,
              toastMessage: uploadState.toastMessage,
            }}
            interimText={interimText}
            activeSessionFiles={activeSessionFiles}
            onRemoveFile={unlinkFile}
            sttSupported={sttSupported}
          />
        </div>

        <footer className={styles.footer}>
          {system ? (
            <>
              Local · {system.voice.stt_model ? `STT: ${system.voice.stt_model}` : 'Web Speech API'} · TTS: {system.voice.tts_backend} ({system.voice.tts_voice})
            </>
          ) : (
            <>Local · Web Speech API · TTS via Kokoro/Edge</>
          )}
        </footer>
      </div>

      <Telemetry
        system={system}
        phases={phases}
        isOpen={telemetryOpen}
        onClose={() => setTelemetryOpen(false)}
      />

      <Memories
        isOpen={memoriesOpen}
        onClose={() => setMemoriesOpen(false)}
      />
      <ConfirmModal
        isOpen={showClearConfirm}
        title="Clear Transcript"
        message="Are you sure you want to wipe the active session's dialogue history? This action is irreversible."
        confirmLabel="Wipe history"
        onConfirm={() => {
          clearChat();
          setShowClearConfirm(false);
        }}
        onClose={() => setShowClearConfirm(false)}
      />
    </div>
  );
}

export default App;
