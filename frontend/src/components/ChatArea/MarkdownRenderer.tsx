import React, { useState, useEffect, useRef } from 'react';
import styles from './ChatArea.module.css';
import mdStyles from './MarkdownRenderer.module.css';
import { authFetch } from '../../lib/api';

// ── KaTeX (lazy import to keep initial bundle small) ───────────
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let katex: any = null;
import('katex').then(m => { katex = m.default ?? m; }).catch(() => {});
import 'katex/dist/katex.min.css';


// ── Mermaid (lazy import) ───────────────────────────────────────
let mermaidApi: typeof import('mermaid').default | null = null;
import('mermaid').then(m => { mermaidApi = m.default; mermaidApi?.initialize({ startOnLoad: false, theme: 'neutral' }); }).catch(() => {});

// ─────────────────────────────────────────────────────────────────────────────
// CodeBlock sub-component (has own state for Run output)
// ─────────────────────────────────────────────────────────────────────────────
interface CodeBlockProps {
  lang: string;
  code: string;
  blockKey: string;
}

function CodeBlock({ lang, code, blockKey }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState<{ stdout: string; stderr: string; exit_code: number; status: string } | null>(null);
  const [showOutput, setShowOutput] = useState(false);

  const canRun = ['python', 'py'].includes(lang.toLowerCase());

  const handleCopy = async () => {
    try { await navigator.clipboard.writeText(code); } catch { /* ignore */ }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRun = async () => {
    setRunning(true);
    setShowOutput(true);
    setOutput(null);
    try {
      const res = await authFetch('/api/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, language: lang }),
      });
      if (!res.ok) { throw new Error(`HTTP ${res.status}`); }
      const data = await res.json();
      setOutput(data);
    } catch (e) {
      setOutput({ stdout: '', stderr: String(e), exit_code: -1, status: 'error' });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className={mdStyles.codeWrap} key={blockKey}>
      <div className={mdStyles.codeHeader}>
        <span className={mdStyles.codeLang}>{lang || 'code'}</span>
        <div className={mdStyles.codeActions}>
          {canRun && (
            <button
              type="button"
              className={`${mdStyles.codeBtn} ${mdStyles.runBtn}`}
              onClick={handleRun}
              disabled={running}
              title="Run code"
            >
              {running ? '⏳' : '▶ Run'}
            </button>
          )}
          <button
            type="button"
            className={mdStyles.codeBtn}
            onClick={handleCopy}
            title="Copy to clipboard"
          >
            {copied ? '✓ Copied' : 'Copy'}
          </button>
        </div>
      </div>
      <pre className={mdStyles.codePre}><code className={mdStyles.codeBody}>{code}</code></pre>

      {showOutput && (
        <div className={`${mdStyles.outputDrawer} ${output ? (output.exit_code === 0 ? mdStyles.outputOk : mdStyles.outputErr) : ''}`}>
          {running && <span className={mdStyles.outputLoading}>Running…</span>}
          {output && (
            <>
              {output.stdout && <pre className={mdStyles.outputText}>{output.stdout}</pre>}
              {output.stderr && <pre className={mdStyles.outputStderr}>{output.stderr}</pre>}
              {!output.stdout && !output.stderr && (
                <span className={mdStyles.outputEmpty}>No output</span>
              )}
              <span className={mdStyles.outputMeta}>Exit {output.exit_code} · {output.status}</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MermaidBlock sub-component
// ─────────────────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────────────────
// MermaidBlock sub-component
// ─────────────────────────────────────────────────────────────────────────────
function autoFixMermaid(code: string): string {
  let lines = code.split('\n');
  lines = lines.map(line => {
    // Stadium: id([label])
    line = line.replace(/([a-zA-Z0-9_-]+)\s*\(\[\s*([^"]+?)\s*\]\)/g, (match, id, label) => {
      if (label.includes('(') || label.includes(')') || label.includes('[') || label.includes(']') || label.includes(':') || label.includes('-') || label.includes('/') || label.includes('\\') || label.includes('&') || label.includes('%')) {
        return `${id}(["${label.replace(/"/g, '\\"')}"])`;
      }
      return match;
    });
    // Subroutine: id[[label]]
    line = line.replace(/([a-zA-Z0-9_-]+)\s*\[\[\s*([^"]+?)\s*\]\]/g, (match, id, label) => {
      if (label.includes('(') || label.includes(')') || label.includes('[') || label.includes(']') || label.includes(':') || label.includes('-') || label.includes('/') || label.includes('\\') || label.includes('&') || label.includes('%')) {
        return `${id}[["${label.replace(/"/g, '\\"')}"]]`;
      }
      return match;
    });
    // Circle: id((label))
    line = line.replace(/([a-zA-Z0-9_-]+)\s*\(\(\s*([^"]+?)\s*\)\)/g, (match, id, label) => {
      if (label.includes('(') || label.includes(')') || label.includes('[') || label.includes(']') || label.includes(':') || label.includes('-') || label.includes('/') || label.includes('\\') || label.includes('&') || label.includes('%')) {
        return `${id}(("${label.replace(/"/g, '\\"')}"))`;
      }
      return match;
    });
    // Hexagon: id{{label}}
    line = line.replace(/([a-zA-Z0-9_-]+)\s*\{\{\s*([^"]+?)\s*\}\}/g, (match, id, label) => {
      if (label.includes('(') || label.includes(')') || label.includes('[') || label.includes(']') || label.includes(':') || label.includes('-') || label.includes('/') || label.includes('\\') || label.includes('&') || label.includes('%')) {
        return `${id}{{"${label.replace(/"/g, '\\"')}"}}`;
      }
      return match;
    });
    // Parallelogram / Trapezoids
    line = line.replace(/([a-zA-Z0-9_-]+)\s*\[([\/\\])\s*([^"]+?)\s*([\/\\])\]/g, (match, id, slash1, label, slash2) => {
      if (label.includes('(') || label.includes(')') || label.includes('[') || label.includes(']') || label.includes(':') || label.includes('-') || label.includes('/') || label.includes('\\') || label.includes('&') || label.includes('%')) {
        return `${id}[${slash1}"${label.replace(/"/g, '\\"')}"${slash2}]`;
      }
      return match;
    });
    // Basic Square: id[label]
    line = line.replace(/([a-zA-Z0-9_-]+)\s*\[\s*([^"\[\]]+?)\s*\]/g, (match, id, label) => {
      if (label.includes('(') || label.includes(')') || label.includes(':') || label.includes('-') || label.includes('/') || label.includes('\\') || label.includes('&') || label.includes('%') || label.includes('.') || label.includes(' ')) {
        return `${id}["${label.replace(/"/g, '\\"')}"]`;
      }
      return match;
    });
    // Basic Round: id(label)
    line = line.replace(/([a-zA-Z0-9_-]+)\s*\(\s*([^"\(\)]+?)\s*\)/g, (match, id, label) => {
      if (label.includes('[') || label.includes(']') || label.includes(':') || label.includes('-') || label.includes('/') || label.includes('\\') || label.includes('&') || label.includes('%') || label.includes('.') || label.includes(' ')) {
        return `${id}("${label.replace(/"/g, '\\"')}")`;
      }
      return match;
    });
    // Basic Rhombus: id{label}
    line = line.replace(/([a-zA-Z0-9_-]+)\s*\{\s*([^"\{\}]+?)\s*\}/g, (match, id, label) => {
      if (label.includes('(') || label.includes(')') || label.includes('[') || label.includes(']') || label.includes(':') || label.includes('-') || label.includes('/') || label.includes('\\') || label.includes('&') || label.includes('%') || label.includes('.') || label.includes(' ')) {
        return `${id}{"${label.replace(/"/g, '\\"').replace(/\{/g, '').replace(/\}/g, '')}"}`;
      }
      return match;
    });

    return line;
  });
  return lines.join('\n');
}

function MermaidBlock({ code, id }: { code: string; id: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!mermaidApi || !ref.current) return;
    const el = ref.current;
    el.innerHTML = '';
    setError('');
    const fixedCode = autoFixMermaid(code);
    mermaidApi.render(`mermaid-${id}`, fixedCode)
      .then(({ svg }) => { if (ref.current) ref.current.innerHTML = svg; })
      .catch((e: Error) => setError(e.message || 'Diagram error'));
  }, [code, id]);

  if (error) {
    return (
      <div className={mdStyles.callout} style={{ borderLeftColor: 'var(--callout-caution-border)', background: 'var(--callout-caution)', padding: '12px' }}>
        <div style={{ fontWeight: 'bold', marginBottom: '8px' }}>⚠️ Mermaid Render Error: {error}</div>
        <details>
          <summary style={{ cursor: 'pointer', fontSize: '13px', opacity: 0.8 }}>Show original diagram code</summary>
          <pre style={{ marginTop: '8px', fontSize: '12px', background: 'rgba(0,0,0,0.05)', padding: '8px', borderRadius: '4px', overflowX: 'auto', whiteSpace: 'pre-wrap' }}>{code}</pre>
        </details>
      </div>
    );
  }
  return <div ref={ref} className={mdStyles.mermaidWrap} />;
}

// ─────────────────────────────────────────────────────────────────────────────
// SVG Chart renderer
// ─────────────────────────────────────────────────────────────────────────────
interface ChartData { type: 'bar' | 'line' | 'pie' | 'scatter'; title?: string; labels?: string[]; datasets?: { label?: string; data: number[] }[] }

function ChartBlock({ json }: { json: string }) {
  try {
    const d: ChartData = JSON.parse(json);
    return <SvgChart data={d} />;
  } catch {
    return <CodeBlock lang="json" code={json} blockKey="fallback-chart" />;
  }
}

const PALETTE = ['#4a7c59','#705c30','#3b82f6','#f59e0b','#ef4444','#8b5cf6','#06b6d4'];

function SvgChart({ data }: { data: ChartData }) {
  const W = 520, H = 240, PAD = { top: 36, right: 16, bottom: 48, left: 48 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const labels = data.labels ?? [];
  const sets = data.datasets ?? [];
  const allVals = sets.flatMap(s => s.data);
  const maxVal = Math.max(...allVals, 1);
  const minVal = Math.min(...allVals, 0);
  const range = maxVal - minVal || 1;

  if (data.type === 'pie') {
    const values = sets[0]?.data ?? [];
    const total = values.reduce((a, b) => a + b, 0) || 1;
    let startAngle = -Math.PI / 2;
    const cx = W / 2, cy = H / 2 - 10, r = Math.min(innerW, innerH) / 2 - 10;
    const slices = values.map((v, i) => {
      const angle = (v / total) * 2 * Math.PI;
      const x1 = cx + r * Math.cos(startAngle), y1 = cy + r * Math.sin(startAngle);
      const x2 = cx + r * Math.cos(startAngle + angle), y2 = cy + r * Math.sin(startAngle + angle);
      const large = angle > Math.PI ? 1 : 0;
      const path = `M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${large},1 ${x2},${y2} Z`;
      const midA = startAngle + angle / 2;
      const lx = cx + (r * 0.65) * Math.cos(midA), ly = cy + (r * 0.65) * Math.sin(midA);
      startAngle += angle;
      return { path, lx, ly, label: labels[i] ?? i, color: PALETTE[i % PALETTE.length], pct: ((v / total) * 100).toFixed(1) };
    });
    return (
      <div className={mdStyles.chartWrap}>
        {data.title && <div className={mdStyles.chartTitle}>{data.title}</div>}
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 260 }}>
          {slices.map((s, i) => (
            <g key={i}><path d={s.path} fill={s.color} opacity={0.9} /><text x={s.lx} y={s.ly} textAnchor="middle" fill="#fff" fontSize="11" fontWeight="600">{s.pct}%</text></g>
          ))}
        </svg>
        <div className={mdStyles.chartLegend}>{slices.map((s, i) => <span key={i} className={mdStyles.legendItem}><span style={{ background: s.color }} className={mdStyles.legendDot} />{String(s.label)}</span>)}</div>
      </div>
    );
  }

  const barW = data.type === 'bar' ? (innerW / Math.max(labels.length, 1)) * 0.7 : 0;
  const barGap = data.type === 'bar' ? (innerW / Math.max(labels.length, 1)) * 0.3 : 0;
  const xStep = innerW / Math.max(labels.length - 1, 1);

  const toY = (v: number) => PAD.top + innerH - ((v - minVal) / range) * innerH;
  const toX = (i: number) => data.type === 'bar'
    ? PAD.left + i * (barW + barGap) + barGap / 2
    : PAD.left + i * xStep;

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(t => minVal + t * range);

  return (
    <div className={mdStyles.chartWrap}>
      {data.title && <div className={mdStyles.chartTitle}>{data.title}</div>}
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ maxHeight: 300 }}>
        {/* Grid + Y-axis labels */}
        {yTicks.map((v, i) => {
          const y = toY(v);
          return (
            <g key={i}>
              <line x1={PAD.left} y1={y} x2={PAD.left + innerW} y2={y} stroke="rgba(46,50,48,0.1)" strokeDasharray="4,4" />
              <text x={PAD.left - 6} y={y + 4} textAnchor="end" fontSize="10" fill="var(--text-muted)">{Math.round(v)}</text>
            </g>
          );
        })}
        {/* X-axis labels */}
        {labels.map((lbl, i) => (
          <text key={i} x={data.type === 'bar' ? toX(i) + barW / 2 : toX(i)} y={H - PAD.bottom + 16} textAnchor="middle" fontSize="10" fill="var(--text-muted)">{String(lbl).slice(0, 10)}</text>
        ))}
        {/* Datasets */}
        {sets.map((s, si) => {
          const color = PALETTE[si % PALETTE.length];
          if (data.type === 'bar') {
            return s.data.map((v, i) => {
              const bH = ((v - minVal) / range) * innerH;
              return <rect key={i} x={toX(i)} y={toY(v)} width={barW} height={bH} fill={color} rx={3} opacity={0.85} />;
            });
          }
          if (data.type === 'line' || data.type === 'scatter') {
            const pts = s.data.map((v, i) => `${toX(i)},${toY(v)}`).join(' ');
            return (
              <g key={si}>
                {data.type === 'line' && <polyline points={pts} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" />}
                {s.data.map((v, i) => <circle key={i} cx={toX(i)} cy={toY(v)} r={4} fill={color} />)}
              </g>
            );
          }
          return null;
        })}
      </svg>
      {sets.length > 1 && (
        <div className={mdStyles.chartLegend}>{sets.map((s, i) => <span key={i} className={mdStyles.legendItem}><span style={{ background: PALETTE[i % PALETTE.length] }} className={mdStyles.legendDot} />{s.label ?? `Series ${i + 1}`}</span>)}</div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Callout renderer
// ─────────────────────────────────────────────────────────────────────────────
const CALLOUT_ICONS: Record<string, string> = { NOTE: 'ℹ️', TIP: '💡', WARNING: '⚠️', CAUTION: '🔴', IMPORTANT: '🔔' };
const CALLOUT_VARS: Record<string, [string, string]> = {
  NOTE: ['--callout-note', '--callout-note-border'],
  TIP: ['--callout-tip', '--callout-tip-border'],
  WARNING: ['--callout-warn', '--callout-warn-border'],
  CAUTION: ['--callout-caution', '--callout-caution-border'],
  IMPORTANT: ['--callout-important', '--callout-important-border'],
};

// ─────────────────────────────────────────────────────────────────────────────
// LaTeX inline helper
// ─────────────────────────────────────────────────────────────────────────────
function renderLatex(text: string, displayMode: boolean): React.ReactNode {
  if (!katex) return <span>{text}</span>;
  try {
    const html = katex.renderToString(text, { displayMode, throwOnError: false, output: 'html' });
    return <span dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    return <span>{text}</span>;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Inline renderer: bold, italic, code, links, inline LaTeX
// ─────────────────────────────────────────────────────────────────────────────
function renderInline(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let key = 0;
  // Token: inline-code, bold, italic, link, inline-latex
  const tok = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\)|\$[^$\n]+?\$)/g;
  const subs = text.split(tok);
  subs.forEach(part => {
    if (!part) return;
    if (part.startsWith('`') && part.endsWith('`')) {
      parts.push(<code key={key++} className={mdStyles.inlineCode}>{part.slice(1, -1)}</code>);
    } else if (part.startsWith('**') && part.endsWith('**')) {
      parts.push(<strong key={key++}>{part.slice(2, -2)}</strong>);
    } else if (part.startsWith('*') && part.endsWith('*')) {
      parts.push(<em key={key++}>{part.slice(1, -1)}</em>);
    } else if (part.startsWith('[') && part.includes('](')) {
      const m = part.match(/\[([^\]]+)\]\(([^)]+)\)/);
      if (m) parts.push(<a key={key++} href={m[2]} target="_blank" rel="noopener noreferrer" className={mdStyles.link}>{m[1]}</a>);
      else parts.push(part);
    } else if (part.startsWith('$') && part.endsWith('$') && part.length > 2) {
      parts.push(<span key={key++}>{renderLatex(part.slice(1, -1), false)}</span>);
    } else {
      parts.push(part);
    }
  });
  return parts;
}

// ─────────────────────────────────────────────────────────────────────────────
// Main block parser
// ─────────────────────────────────────────────────────────────────────────────
function parseBlocks(text: string, mermaidCounter: { n: number }): React.ReactNode[] {
  const lines = text.split('\n');
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let bk = 0;

  while (i < lines.length) {
    const line = lines[i];

    // ── Empty line ───
    if (!line.trim()) { i++; continue; }

    // ── Block LaTeX $$ ... $$ ───
    if (line.trim().startsWith('$$')) {
      const latexLines: string[] = [];
      const inner = line.trim().slice(2);
      if (inner.endsWith('$$') && inner.length > 2) {
        blocks.push(<div key={bk++} className={mdStyles.latexBlock}>{renderLatex(inner.slice(0, -2), true)}</div>);
        i++; continue;
      }
      if (inner) latexLines.push(inner);
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('$$')) { latexLines.push(lines[i]); i++; }
      i++; // skip closing $$
      blocks.push(<div key={bk++} className={mdStyles.latexBlock}>{renderLatex(latexLines.join('\n'), true)}</div>);
      continue;
    }

    // ── Fenced code block `` ` `` `` ` `` `` ` `` ───
    if (line.trim().startsWith('```')) {
      const lang = line.trim().slice(3).trim().toLowerCase();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) { codeLines.push(lines[i]); i++; }
      i++; // skip closing ```
      const code = codeLines.join('\n');

      if (lang === 'mermaid') {
        const mid = `${bk}-${mermaidCounter.n++}`;
        blocks.push(<MermaidBlock key={bk++} code={code} id={mid} />);
      } else if (lang === 'chart') {
        blocks.push(<ChartBlock key={bk++} json={code} />);
      } else {
        blocks.push(<CodeBlock key={bk++} lang={lang} code={code} blockKey={`cb-${bk}`} />);
      }
      continue;
    }

    // ── GFM callout: > [!TYPE] or > [!TYPE]\n> text ───
    if (line.trim().startsWith('>')) {
      const calloutLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        calloutLines.push(lines[i].trim().slice(1).trimStart());
        i++;
      }
      const joined = calloutLines.join('\n');
      const calloutMatch = joined.match(/^\[!(NOTE|TIP|WARNING|CAUTION|IMPORTANT)\]\s*([\s\S]*)/i);
      if (calloutMatch) {
        const type = calloutMatch[1].toUpperCase();
        const body = calloutMatch[2].trim();
        const [bg, border] = CALLOUT_VARS[type] ?? ['--callout-note', '--callout-note-border'];
        blocks.push(
          <div key={bk++} className={mdStyles.callout} style={{ background: `var(${bg})`, borderLeftColor: `var(${border})` }}>
            <span className={mdStyles.calloutIcon}>{CALLOUT_ICONS[type] ?? 'ℹ️'}</span>
            <span className={mdStyles.calloutType}>{type}</span>
            <span className={mdStyles.calloutBody}>{renderInline(body)}</span>
          </div>
        );
      } else {
        blocks.push(<blockquote key={bk++} className={mdStyles.blockquote}>{renderInline(joined)}</blockquote>);
      }
      continue;
    }

    // ── Horizontal rule ───
    if (/^[-*_]{3,}$/.test(line.trim())) {
      blocks.push(<hr key={bk++} className={mdStyles.hr} />);
      i++; continue;
    }

    // ── Heading ───
    const hm = line.match(/^(#{1,6})\s+(.*)/);
    if (hm) {
      const lvl = hm[1].length;
      const headingNode = React.createElement(
        `h${lvl}`,
        { key: bk++, className: mdStyles.heading },
        ...renderInline(hm[2])
      );
      blocks.push(headingNode);
      i++; continue;
    }

    // ── Table ───
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        tableLines.push(lines[i].trim());
        i++;
      }
      if (tableLines.length >= 2) {
        const headers = tableLines[0].split('|').slice(1, -1).map(c => c.trim());
        const rows = tableLines.slice(2).map(r => r.split('|').slice(1, -1).map(c => c.trim()));
        blocks.push(
          <div key={bk++} className={mdStyles.tableWrap}>
            <table className={mdStyles.table}>
              <thead><tr>{headers.map((h, hi) => <th key={hi} className={mdStyles.th}>{renderInline(h)}</th>)}</tr></thead>
              <tbody>{rows.map((row, ri) => (
                <tr key={ri} className={ri % 2 === 0 ? mdStyles.trOdd : mdStyles.trEven}>
                  {row.map((cell, ci) => <td key={ci} className={mdStyles.td}>{renderInline(cell)}</td>)}
                </tr>
              ))}</tbody>
            </table>
          </div>
        );
      }
      continue;
    }

    // ── Checklist item ── `- [ ]` or `- [x]` ───
    const checkMatch = line.match(/^[-*+]\s+\[([ xX])\]\s+(.*)/);
    if (checkMatch) {
      const checkItems: React.ReactNode[] = [];
      let ck = 0;
      while (i < lines.length) {
        const cm = lines[i].match(/^[-*+]\s+\[([ xX])\]\s+(.*)/);
        if (!cm) break;
        const checked = cm[1].toLowerCase() === 'x';
        checkItems.push(
          <li key={ck++} className={mdStyles.checkItem}>
            <span className={`${mdStyles.checkbox} ${checked ? mdStyles.checkboxChecked : ''}`}>{checked ? '✓' : ''}</span>
            <span>{renderInline(cm[2])}</span>
          </li>
        );
        i++;
      }
      blocks.push(<ul key={bk++} className={mdStyles.checkList}>{checkItems}</ul>);
      continue;
    }

    // ── Ordered list ───
    if (/^\d+\.\s/.test(line)) {
      const items: React.ReactNode[] = [];
      let lk = 0;
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        const m = lines[i].match(/^\d+\.\s+(.*)/);
        items.push(<li key={lk++} className={mdStyles.li}>{renderInline(m ? m[1] : lines[i])}</li>);
        i++;
      }
      blocks.push(<ol key={bk++} className={mdStyles.ol}>{items}</ol>);
      continue;
    }

    // ── Unordered list ───
    if (/^[-*+]\s/.test(line)) {
      const items: React.ReactNode[] = [];
      let lk = 0;
      while (i < lines.length && /^[-*+]\s/.test(lines[i])) {
        const m = lines[i].match(/^[-*+]\s+(.*)/);
        items.push(<li key={lk++} className={mdStyles.li}>{renderInline(m ? m[1] : lines[i])}</li>);
        i++;
      }
      blocks.push(<ul key={bk++} className={mdStyles.ul}>{items}</ul>);
      continue;
    }

    // ── Plain paragraph ───
    blocks.push(<p key={bk++} className={mdStyles.para}>{renderInline(line)}</p>);
    i++;
  }

  return blocks;
}

// ─────────────────────────────────────────────────────────────────────────────
// Cursor append utility (for streaming)
// ─────────────────────────────────────────────────────────────────────────────
function appendCursor(node: React.ReactNode, cursor: React.ReactNode): React.ReactNode {
  if (!node) return cursor;
  if (typeof node === 'string') return <>{node}{cursor}</>;
  if (Array.isArray(node)) {
    if (!node.length) return [cursor];
    const last = node.length - 1;
    return [...node.slice(0, last), appendCursor(node[last], cursor)];
  }
  if (React.isValidElement(node)) {
    const t = node.type;
    if (t === 'hr' || t === 'br' || t === 'img') return <>{node}{cursor}</>;
    const ch = (node.props as Record<string, unknown>).children;
    if (ch === undefined || ch === null) return React.cloneElement(node as React.ReactElement, undefined, cursor);
    return React.cloneElement(node as React.ReactElement, undefined, appendCursor(ch as React.ReactNode, cursor));
  }
  return <>{node}{cursor}</>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Public component
// ─────────────────────────────────────────────────────────────────────────────
interface MarkdownRendererProps { content: string; isStreaming?: boolean; }

export function MarkdownRenderer({ content, isStreaming }: MarkdownRendererProps) {
  const mermaidCounter = { n: 0 };
  const blocks = parseBlocks(content, mermaidCounter);

  // If streaming with no content yet — show a standalone blinking cursor
  if (isStreaming && blocks.length === 0) {
    return <div className={mdStyles.root}>{'\u200B'}<span className={styles.cursor} /></div>;
  }

  if (isStreaming && blocks.length > 0) {
    const last = blocks.length - 1;
    const cursor = <span className={styles.cursor} />;
    blocks[last] = appendCursor(blocks[last], cursor);
  }

  return <div className={mdStyles.root}>{blocks}</div>;
}
