import { useState, useEffect, useCallback } from 'react';
import { Trash2, Database, RefreshCw } from 'lucide-react';
import styles from './Memories.module.css';
import { authFetch } from '../../lib/api';

interface Memory {
  id: number;
  content: string;
  category: string;
  importance: number;
  created_at: string;
}

interface MemoriesProps {
  isOpen: boolean;
  onClose: () => void;
}

export function Memories({ isOpen, onClose }: MemoriesProps) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

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

  useEffect(() => {
    if (isOpen) fetchMemories();
  }, [isOpen, fetchMemories]);

  const handleDelete = async (id: number) => {
    try {
      await authFetch(`/api/memories/${id}`, { method: 'DELETE' });
      setMemories(prev => prev.filter(m => m.id !== id));
      setTotal(prev => prev - 1);
    } catch {}
  };

  if (!isOpen) return null;

  return (
    <div className={styles.overlay}>
      <div className={styles.panel}>
        <div className={styles.header}>
          <div className={styles.headerTitle}>
            <Database size={18} />
            <h2>Memories ({total})</h2>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.btnIcon} onClick={fetchMemories} title="Refresh">
              <RefreshCw size={16} />
            </button>
            <button className={styles.btnIcon} onClick={onClose} title="Close">
              ✕
            </button>
          </div>
        </div>

        <div className={styles.list}>
          {loading && <p className={styles.empty}>Loading...</p>}
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
      </div>
    </div>
  );
}
