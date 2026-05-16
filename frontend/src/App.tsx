import { useState, useCallback } from 'react';
import { Header } from './components/Header/Header';
import { ChatArea } from './components/ChatArea/ChatArea';
import { Composer } from './components/Composer/Composer';
import { Telemetry } from './components/Telemetry/Telemetry';
import { Memories } from './components/Memories/Memories';
import { useSystem } from './hooks/useSystem';
import { useChat } from './hooks/useChat';
import { useVoice } from './hooks/useVoice';
import { useFileUpload } from './hooks/useFileUpload';
import styles from './App.module.css';

function App() {
  const [statusText, setStatusText] = useState('Online');
  const [telemetryOpen, setTelemetryOpen] = useState(false);
  const [memoriesOpen, setMemoriesOpen] = useState(false);
  const [interimText, setInterimText] = useState('');

  const { system, fetchSystem } = useSystem();
  const uploadState = useFileUpload();

  const handleStatusChange = useCallback((status: string, busy: boolean) => {
    setStatusText(status);
    if (!busy) fetchSystem();
  }, [fetchSystem]);

  const { isRecording, isPlaying, toggleRecording, stopAudio, queueTTS } = useVoice(
    (text) => { setInterimText(''); handleSend(text, true); },
    (text) => setInterimText(text),
  );

  const { messages, phases, isBusy: chatBusy, sendMessage, clearChat, addSystemMessage } =
    useChat(handleStatusChange, queueTTS);

  const handleSend = async (text: string, isVoiceMode: boolean) => {
    stopAudio();
    await sendMessage(text, isVoiceMode);
  };

  const handleUpload = async (file: File) => {
    const data = await uploadState.uploadFile(file);
    if (data) {
      addSystemMessage(
        `I've ingested **${data.filename}** into my knowledge base, sir. ` +
        `It's been split into ${data.chunks} searchable chunks (~${data.words} words total). ` +
        `You can now ask me questions about its contents.`
      );
    }
  };

  return (
    <div className={styles.layout}>
      <div className={styles.mainCol}>
        <Header
          version={system?.ui?.version || 'v2.1 Sentinel'}
          statusText={statusText}
          isBusy={chatBusy}
          onClearChat={clearChat}
          onToggleTelemetry={() => setTelemetryOpen(o => !o)}
          onToggleMemories={() => setMemoriesOpen(o => !o)}
        />

        <ChatArea
          messages={messages}
          isSpeaking={isPlaying}
          onDropFile={handleUpload}
        />

        <div className={styles.composerWrap}>
          <Composer
            onSend={handleSend}
            isBusy={chatBusy}
            isRecording={isRecording}
            onToggleRecord={toggleRecording}
            onUpload={handleUpload}
            uploadState={{
              isUploading: uploadState.isUploading,
              toastMessage: uploadState.toastMessage,
            }}
            interimText={interimText}
          />
        </div>

        <footer className={styles.footer}>
          Local · Web Speech API · TTS via Kokoro/Edge
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
    </div>
  );
}

export default App;
