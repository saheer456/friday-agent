import styles from './Header.module.css';

interface HeaderProps {
  version: string;
  statusText: string;
  isBusy: boolean;
  onClearChat: () => void;
}

export function Header({ version, statusText, isBusy, onClearChat }: HeaderProps) {
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
      </div>
    </header>
  );
}
