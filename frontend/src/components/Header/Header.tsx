import styles from './Header.module.css';
import { Activity, Database, LogOut, Menu, Trash2, Pause, Play } from 'lucide-react';

interface HeaderProps {
  version: string;
  statusText: string;
  isBusy: boolean;
  isSpeaking?: boolean;
  isPaused?: boolean;
  onClearChat: () => void;
  onToggleTelemetry: () => void;
  onToggleMemories: () => void;
  onLogout: () => void;
  onToggleSidebar?: () => void;
  onTogglePause?: () => void;
  fullAccess?: boolean;
}

export function Header({
  version,
  statusText,
  isBusy,
  isSpeaking = false,
  isPaused = false,
  onClearChat,
  onToggleTelemetry,
  onToggleMemories,
  onLogout,
  onToggleSidebar,
  onTogglePause,
  fullAccess = true,
}: HeaderProps) {
  return (
    <header className={styles.header}>

      {/* ── Left: sidebar toggle ─── */}
      <div className={styles.left}>
        {onToggleSidebar && (
          <button
            type="button"
            className={styles.iconBtn}
            onClick={onToggleSidebar}
            aria-label="Toggle chat history"
            title="Toggle chat history"
          >
            <Menu size={18} />
          </button>
        )}
      </div>

      {/* ── Center: brand ─── */}
      <div className={styles.brand}>
        <span
          className={[
            styles.speakDot,
            isSpeaking ? styles.speakDotActive : '',
            isBusy && !isSpeaking ? styles.speakDotBusy : '',
          ].join(' ')}
          aria-label={isSpeaking ? 'Speaking' : isBusy ? 'Thinking' : ''}
        />
        <h1 className={styles.title}>F.R.I.D.A.Y</h1>
        <span className={styles.versionPill}>{version}</span>
      </div>

      {/* ── Right: actions ─── */}
      <div className={styles.actions}>
        {isSpeaking && onTogglePause && (
          <button
            type="button"
            className={styles.pauseBtn}
            onClick={onTogglePause}
            aria-label={isPaused ? 'Resume audio' : 'Pause audio'}
            title={isPaused ? 'Resume audio' : 'Pause audio'}
          >
            {isPaused ? <Play size={16} /> : <Pause size={16} />}
          </button>
        )}

        <span className={styles.statusText}>{statusText}</span>

        <button
          type="button"
          className={styles.iconBtn}
          onClick={onClearChat}
          aria-label="Clear chat"
          title="Clear chat"
        >
          <Trash2 size={16} />
        </button>

        {fullAccess && (
          <button
            type="button"
            className={styles.iconBtn}
            onClick={onToggleMemories}
            aria-label="Memory & Knowledge Graph"
            title="Memory & Knowledge Graph"
          >
            <Database size={16} />
          </button>
        )}

        {fullAccess && (
          <button
            type="button"
            className={styles.iconBtn}
            onClick={onToggleTelemetry}
            aria-label="Toggle telemetry"
            title="Toggle telemetry"
          >
            <Activity size={16} />
          </button>
        )}

        <button
          type="button"
          className={`${styles.iconBtn} ${styles.logoutBtn}`}
          onClick={onLogout}
          aria-label="Log out"
          title="Log out"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}