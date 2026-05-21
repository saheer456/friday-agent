import { useRef } from 'react';
import { Mic, Paperclip, Send } from 'lucide-react';
import styles from './Composer.module.css';

interface ComposerProps {
  value: string;
  onChange: (val: string) => void;
  onSend: (text: string, isVoiceMode: boolean) => void;
  isBusy: boolean;
  isRecording: boolean;
  onToggleRecord: () => void;
  onUpload: (file: File) => void;
  uploadState: { isUploading: boolean; toastMessage: { text: string; type: string } | null };
  interimText?: string;
  allowUpload?: boolean;
  activeSessionFiles?: string[];
  onRemoveFile?: (filename: string) => void;
}

export function Composer({ value, onChange, onSend, isBusy, isRecording, onToggleRecord, onUpload, uploadState, interimText, allowUpload = true, activeSessionFiles = [], onRemoveFile }: ComposerProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const autoGrow = () => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 180) + 'px';
    }
  };

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (isBusy || !value.trim()) return;
    onSend(value.trim(), isRecording);
    onChange('');
    setTimeout(autoGrow, 0);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      onUpload(e.target.files[0]);
      e.target.value = '';
    }
  };

  return (
    <div style={{ position: 'relative' }}>
      {activeSessionFiles && activeSessionFiles.length > 0 && (
        <div className={styles.attachedFiles}>
          {activeSessionFiles.map((file, idx) => (
            <div key={idx} className={styles.filePill} title={file}>
              <Paperclip size={12} className={styles.filePillIcon} />
              <span className={styles.filePillName}>{file}</span>
              {onRemoveFile && (
                <button
                  type="button"
                  className={styles.filePillRemove}
                  onClick={() => onRemoveFile(file)}
                  title="Remove document from context"
                >
                  &times;
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {uploadState.toastMessage && (

        <div className={`${styles.uploadToast} ${uploadState.toastMessage.type ? styles[uploadState.toastMessage.type] : ''}`}>
          <Paperclip size={14} />
          <span>{uploadState.toastMessage.text}</span>
        </div>
      )}

      <form className={styles.composer} onSubmit={handleSubmit} autoComplete="off">
        <div className={styles.inputGlow}></div>
        
        {allowUpload && (
          <>
            <input
              type="file"
              ref={fileInputRef}
              accept=".pdf,.docx,.txt,.md,.csv,.json,.py,.js,.ts,.tsx,.jsx,.html,.css,.sh,.bat,.sql,.yaml,.yml,.toml,.xml,.ini,.cfg,.log,.env"
              hidden
              onChange={handleFileChange}
            />

            <button
              type="button"
              className={`${styles.btn} ${styles.upload} ${uploadState.isUploading ? styles.uploading : ''}`}
              onClick={() => fileInputRef.current?.click()}
              title="Attach a file"
            >
              <Paperclip size={18} />
            </button>
          </>
        )}

        <textarea
          ref={inputRef}
          className={styles.textarea}
          rows={1}
          value={value}
          placeholder={isRecording && interimText ? interimText : "Message FRIDAY…"}
          maxLength={16000}
          onChange={(e) => {
            onChange(e.target.value);
            autoGrow();
          }}
          onKeyDown={handleKeyDown}
        />

        <button 
          type="button" 
          className={`${styles.btn} ${styles.voice} ${isRecording ? styles.recording : ''}`}
          onClick={onToggleRecord}
          title="Voice input"
        >
          <Mic size={20} />
        </button>

        <button 
          type="submit" 
          className={`${styles.btn} ${styles.send} ${isBusy ? styles.sending : ''}`}
          disabled={isBusy}
        >
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
