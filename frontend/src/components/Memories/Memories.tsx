import { useState, useEffect, useCallback } from 'react';
import { Trash2, Database, RefreshCw, Share2, Search } from 'lucide-react';
import styles from './Memories.module.css';
import { authFetch } from '../../lib/api';

interface Memory {
  id: number;
  content: string;
  category: string;
  importance: number;
  created_at: string;
}

interface GraphNode {
  id: string;
  name: string;
  type: string;
  description?: string;
}

interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  weight: number;
}

interface MemoriesProps {
  isOpen: boolean;
  onClose: () => void;
}

type Tab = 'memories' | 'graph';

export function Memories({ isOpen, onClose }: MemoriesProps) {
  const [tab, setTab] = useState<Tab>('memories');

  // ── Memories tab state ──────────────────────────────────
  const [memories, setMemories] = useState<Memory[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  // ── Graph tab state ─────────────────────────────────────
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphQuery, setGraphQuery] = useState('');

  const fetchMemories = useCallback(async () => {
    setLoading(true);
    try {
      const r = await authFetch('/api/memories?limit=100');
      const data = await r.json();
      setMemories(data.memories || []);
      setTotal(data.total || 0);
    } catch {
      setMemories([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchGraph = useCallback(async (query?: string) => {
    setGraphLoading(true);
    try {
      const url = query?.trim()
        ? `/api/graph/nodes?q=${encodeURIComponent(query.trim())}`
        : '/api/graph/all?limit=60';
      const r = await authFetch(url);
      const data = await r.json();
      setGraphNodes(data.nodes || []);
      setGraphEdges(data.edges || []);
    } catch {
      setGraphNodes([]);
      setGraphEdges([]);
    } finally {
      setGraphLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    if (tab === 'memories') fetchMemories();
    else fetchGraph();
  }, [isOpen, tab, fetchMemories, fetchGraph]);

  const handleDelete = async (id: number) => {
    try {
      await authFetch(`/api/memories/${id}`, { method: 'DELETE' });
      setMemories(prev => prev.filter(m => m.id !== id));
      setTotal(prev => prev - 1);
    } catch {}
  };

  const handleGraphSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchGraph(graphQuery);
  };

  if (!isOpen) return null;

  return (
    <div className={styles.overlay}>
      <div className={styles.panel}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerTitle}>
            {tab === 'memories' ? <Database size={18} /> : <Share2 size={18} />}
            <h2>
              {tab === 'memories'
                ? `Memories (${total})`
                : `Knowledge Graph (${graphNodes.length} nodes · ${graphEdges.length} edges)`}
            </h2>
          </div>
          <div className={styles.headerActions}>
            <button
              className={styles.btnIcon}
              onClick={() => tab === 'memories' ? fetchMemories() : fetchGraph(graphQuery)}
              title="Refresh"
            >
              <RefreshCw size={16} />
            </button>
            <button className={styles.btnIcon} onClick={onClose} title="Close">✕</button>
          </div>
        </div>

        {/* Tabs */}
        <div className={styles.tabs}>
          <button
            className={`${styles.tab} ${tab === 'memories' ? styles.tabActive : ''}`}
            onClick={() => setTab('memories')}
          >
            <Database size={14} /> Memories
          </button>
          <button
            className={`${styles.tab} ${tab === 'graph' ? styles.tabActive : ''}`}
            onClick={() => setTab('graph')}
          >
            <Share2 size={14} /> Knowledge Graph
          </button>
        </div>

        {/* ── Memories tab ─────────────────────────────── */}
        {tab === 'memories' && (
          <div className={styles.list}>
            {loading && <p className={styles.empty}>Loading…</p>}
            {!loading && memories.length === 0 && (
              <p className={styles.empty}>No memories stored yet.</p>
            )}
            {memories.map(m => (
              <div key={m.id} className={styles.card}>
                <div className={styles.cardHeader}>
                  <span className={`${styles.badge} ${styles[`badge_${m.category}`] || ''}`}>
                    {m.category}
                  </span>
                  <span className={styles.importance}>
                    {Math.round(m.importance * 100)}%
                  </span>
                  <button
                    className={styles.deleteBtn}
                    onClick={() => handleDelete(m.id)}
                    title="Delete memory"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
                <p className={styles.content}>{m.content}</p>
                <span className={styles.date}>
                  {new Date(m.created_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* ── Knowledge Graph tab ───────────────────────── */}
        {tab === 'graph' && (
          <div className={styles.graphPane}>
            <form className={styles.searchBar} onSubmit={handleGraphSearch}>
              <Search size={15} className={styles.searchIcon} />
              <input
                className={styles.searchInput}
                value={graphQuery}
                onChange={e => setGraphQuery(e.target.value)}
                placeholder="Search entities (e.g. python, friday, sqlite)…"
              />
              <button className={styles.searchBtn} type="submit">Search</button>
              {graphQuery && (
                <button
                  className={styles.searchClear}
                  type="button"
                  onClick={() => { setGraphQuery(''); fetchGraph(); }}
                >✕</button>
              )}
            </form>

            {graphLoading && <p className={styles.empty}>Loading graph…</p>}

            {!graphLoading && graphNodes.length === 0 && (
              <p className={styles.empty}>
                {graphQuery ? 'No entities match that query.' : 'No knowledge graph data yet. Chat with FRIDAY to build it.'}
              </p>
            )}

            {!graphLoading && graphNodes.length > 0 && (
              <>
                {/* Nodes */}
                <div className={styles.graphSection}>
                  <p className={styles.graphSectionTitle}>Entities</p>
                  <div className={styles.nodeGrid}>
                    {graphNodes.map(n => (
                      <div key={n.id} className={styles.nodeCard}>
                        <span className={`${styles.nodeTypeBadge} ${styles[`nodeType_${n.type?.toLowerCase()}`] || ''}`}>
                          {n.type}
                        </span>
                        <p className={styles.nodeName}>{n.name}</p>
                        {n.description && (
                          <p className={styles.nodeDesc}>{n.description}</p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Edges */}
                {graphEdges.length > 0 && (
                  <div className={styles.graphSection}>
                    <p className={styles.graphSectionTitle}>Relationships</p>
                    <div className={styles.edgeList}>
                      {graphEdges.map((e, i) => (
                        <div key={i} className={styles.edgeRow}>
                          <span className={styles.edgeNode}>{e.source}</span>
                          <span className={styles.edgeRelation}>{e.relation.replace(/_/g, ' ')}</span>
                          <span className={styles.edgeNode}>{e.target}</span>
                          <span className={styles.edgeWeight}>{Math.round(e.weight * 100)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
