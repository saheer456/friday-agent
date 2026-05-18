import styles from './Header.module.css';
import { Activity, Database, LogOut } from 'lucide-react';

interface HeaderProps {
  version: string;
  statusText: string;
  isBusy: boolean;
  onClearChat: () => void;
  onToggleTelemetry: () => void;
  onToggleMemories: () => void;
  onLogout: () => void;
  fullAccess?: boolean;
}

export function Header({ version, statusText, isBusy, onClearChat, onToggleTelemetry, onToggleMemories, onLogout, fullAccess = true }: HeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.logoRing}>
        <div className={styles.logoCore}></div>
      </div>
      <div className={styles.titles}>
        <div className={styles.titleRow}>
          <h1>F.R.I.D.A.Y</h1>
          <span className={styles.versionPill}>{version}</span>
        </div>
        <p className={styles.tagline}>Full Responsive Interface · Networked Assistant for You</p>
      </div>
      <div className={styles.headerActions}>
        <span className={`${styles.pulseDot} ${isBusy ? styles.busy : ''}`}></span>
        <span className={styles.statusText}>{statusText}</span>
        <button type="button" className={styles.btnClear} onClick={onClearChat}>
          Clear chat
        </button>
        {fullAccess && (
          <button
            type="button"
            className={styles.btnClear}
            onClick={onToggleMemories}
            aria-label="Toggle memories"
          >
            <Database size={18} />
          </button>
        )}
        {/* Mobile: telemetry toggle */}
        {fullAccess && (
          <button
            type="button"
            className={styles.btnTelemetry}
            onClick={onToggleTelemetry}
            aria-label="Toggle telemetry"
          >
            <Activity size={18} />
          </button>
        )}
        <button
          type="button"
          className={styles.btnIcon}
          onClick={onLogout}
          aria-label="Log out"
          title="Log out"
        >
          <LogOut size={18} />
        </button>
      </div>
    </header>
  );
}
