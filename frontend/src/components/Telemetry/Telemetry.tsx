import type { SystemInfo, Phase } from '../../types/api';
import styles from './Telemetry.module.css';

interface TelemetryProps {
  system: SystemInfo | null;
  phases: Phase[];
}

function StatusBadge({ active, label }: { active: boolean; label: string }) {
  return (
    <div className={styles.statusRow}>
      <span className={`${styles.statusBadge} ${active ? styles.active : styles.loading}`}>
        {active ? 'Active' : 'Loading'}
      </span>
      <span className={styles.statusLabel}>{label}</span>
    </div>
  );
}

function SpecGrid({ items }: { items: [string, string][] }) {
  return (
    <dl className={styles.specGrid}>
      {items.length === 0 ? <div className={styles.specSkel}></div> : 
        items.map(([key, val], i) => (
          <div key={i} style={{ display: 'contents' }}>
            <dt>{key}</dt>
            <dd>{val}</dd>
          </div>
        ))
      }
    </dl>
  );
}

export function Telemetry({ system, phases }: TelemetryProps) {
  const rd = system?.readiness || { memory_ready: false, tts_ready: false, stt_ready: true };
  const v = system?.voice || {} as any;
  const L = system?.llm || {} as any;

  return (
    <aside className={styles.telemetry} aria-label="Neural telemetry">
      <div className={styles.telemetryHead}>
        <span className={styles.telemetryDot}></span>
        <h2>Neural Telemetry</h2>
      </div>

      <section className={`${styles.stackCard} ${styles.statusCard}`}>
        <h3>System status</h3>
        <StatusBadge active={rd.memory_ready} label="Memory (MiniLM)" />
        <StatusBadge active={rd.tts_ready} label="TTS Engine" />
        <StatusBadge active={rd.stt_ready} label="STT (Whisper)" />
      </section>

      <section className={styles.stackCard}>
        <h3>Voice stack</h3>
        <SpecGrid items={system ? [
          ['STT', `${v.stt_model || '?'} · ${v.stt_compute || ''}`.trim()],
          ['Device', v.stt_device || 'cpu'],
          ['TTS', v.tts_backend || 'auto'],
          ['Voice', v.tts_voice || '—'],
          ['VAD', `mode ${v.vad_mode ?? '2'}`]
        ] : []} />
      </section>

      <section className={styles.stackCard}>
        <h3>Language uplink</h3>
        <SpecGrid items={system ? [
          ['Provider', L.llm_provider || '—'],
          ['Model', L.llm_model || '—'],
          ['Host', L.llm_url_host || '—'],
          ['Turns', String(system.history_turns ?? 0)]
        ] : []} />
      </section>

      <section className={`${styles.stackCard} ${styles.feedCard}`}>
        <div className={styles.feedHead}>
          <span className={styles.feedPulse}></span>
          <h3>Backend trace</h3>
        </div>
        <div className={styles.phaseFeed}>
          {phases.map((p, i) => (
            <div key={i} className={styles.phaseLine}>
              <span className={styles.phId}>{p.id}</span>
              <div className={styles.phTitle}>{p.title}</div>
              <div className={styles.phDetail}>{p.detail}</div>
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
