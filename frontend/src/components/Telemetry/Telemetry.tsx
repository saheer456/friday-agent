import { useState, useEffect } from 'react';
import type { SystemInfo, Phase } from '../../types/api';
import { authFetch } from '../../lib/api';
import styles from './Telemetry.module.css';

interface TelemetryProps {
  system: SystemInfo | null;
  phases: Phase[];
  isOpen: boolean;
  onClose: () => void;
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

export function Telemetry({ system, phases, isOpen, onClose }: TelemetryProps) {
  const rd = system?.readiness || { memory_ready: false, tts_ready: false, stt_ready: true };
  const v = system?.voice || {} as any;
  const L = system?.llm || {} as any;

  const [providerStats, setProviderStats] = useState<Record<string, { calls: number; errors: number; total_latency_ms: number }>>({});
  const [skillsHealth, setSkillsHealth] = useState<Record<string, { healthy: boolean; configured: boolean; enabled: boolean; exec_count: number; fail_count: number }>>({});

  useEffect(() => {
    if (!isOpen) return;

    let active = true;

    const fetchTelemetryData = async () => {
      try {
        const statsRes = await authFetch('/api/providers/stats');
        if (statsRes.ok && active) {
          const stats = await statsRes.json();
          setProviderStats(stats || {});
        }
      } catch (e) {
        console.error('Failed to fetch provider stats:', e);
      }

      try {
        const healthRes = await authFetch('/api/skills/health');
        if (healthRes.ok && active) {
          const health = await healthRes.json();
          setSkillsHealth(health || {});
        }
      } catch (e) {
        console.error('Failed to fetch skills health:', e);
      }
    };

    fetchTelemetryData();
    const interval = setInterval(fetchTelemetryData, 5000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [isOpen]);

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && <div className={styles.backdrop} onClick={onClose} />}

      <aside
        className={`${styles.telemetry} ${isOpen ? styles.open : ''}`}
        aria-label="Neural telemetry"
      >
        {/* Mobile close button */}
        <button className={styles.closeBtn} onClick={onClose} aria-label="Close telemetry">✕</button>

        <div className={styles.telemetryHead}>
          <span className={styles.telemetryDot}></span>
          <h2>Neural Telemetry</h2>
        </div>

        <section className={`${styles.stackCard} ${styles.statusCard}`}>
          <h3>System status</h3>
          <StatusBadge active={!!rd.memory_ready} label="Local Memory" />
          <StatusBadge active={!!rd.tts_ready} label="TTS Engine" />
          <StatusBadge active={!!rd.stt_ready} label="STT Engine" />
          {rd.vector_store !== undefined && <StatusBadge active={!!rd.vector_store} label="Vector DB (Chroma)" />}
          {rd.supabase !== undefined && <StatusBadge active={!!rd.supabase} label="Supabase Cloud" />}
        </section>

        {rd.providers && Object.keys(rd.providers).length > 0 && (
          <section className={styles.stackCard}>
            <h3>LLM Gateway Health</h3>
            {Object.entries(rd.providers).map(([providerName, healthy]) => (
              <StatusBadge
                key={providerName}
                active={!!healthy}
                label={providerName.toUpperCase()}
              />
            ))}
          </section>
        )}

        {Object.keys(providerStats).length > 0 && (
          <section className={styles.stackCard}>
            <h3>Provider Performance</h3>
            <div className={styles.statsList}>
              {Object.entries(providerStats).map(([name, stat]) => {
                const avgLat = stat.calls > 0 ? (stat.total_latency_ms / stat.calls) : 0;
                return (
                  <div key={name} className={styles.statRow}>
                    <div className={styles.statHeader}>
                      <span className={styles.statName}>{name.toUpperCase()}</span>
                      <span className={styles.statCalls}>{stat.calls} calls</span>
                    </div>
                    <div className={styles.statMetrics}>
                      <span>Errors: {stat.errors}</span>
                      <span>Avg Latency: {avgLat.toFixed(0)}ms</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {Object.keys(skillsHealth).length > 0 && (
          <section className={styles.stackCard}>
            <h3>Skill Engine Status</h3>
            <div className={styles.skillsList}>
              {Object.entries(skillsHealth).map(([name, status]) => (
                <div key={name} className={styles.skillRow}>
                  <div className={styles.skillHeader}>
                    <span className={`${styles.statusIndicator} ${status.healthy ? styles.healthy : styles.unhealthy}`} />
                    <span className={styles.skillName}>{name}</span>
                  </div>
                  <div className={styles.skillMetrics}>
                    <span>Calls: {status.exec_count}</span>
                    <span>Failures: {status.fail_count}</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

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
    </>
  );
}
