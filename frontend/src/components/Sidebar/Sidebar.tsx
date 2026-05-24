import { useState } from 'react';
import { Plus, Trash, Check, Edit3, MessageSquare, ChevronLeft, ChevronRight, Download } from 'lucide-react';
import styles from './Sidebar.module.css';

interface Session {
  id: string;
  title: string;
}

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
  sessions: Session[];
  activeSessionId: string;
  activeSessionFiles: string[];
  onCreateSession: () => void;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onRenameSession: (id: string, newTitle: string) => void;
}

export function Sidebar({
  isOpen,
  onToggle,
  sessions,
  activeSessionId,
  activeSessionFiles,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onRenameSession,
}: SidebarProps) {
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState<string>('');

  const handleExportSession = async (id: string) => {
    try {
      const { authFetch } = await import('../../lib/api');
      const res = await authFetch(`/api/sessions/${id}/export?format=markdown`);
      if (res.ok) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `session_${id}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      }
    } catch (e) {
      console.error('Error exporting session:', e);
    }
  };

  const handleStartRename = (session: Session) => {
    setEditingSessionId(session.id);
    setEditTitle(session.title);
  };

  const handleSaveRename = (id: string) => {
    if (editTitle.trim()) {
      onRenameSession(id, editTitle.trim());
    }
    setEditingSessionId(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent, id: string) => {
    if (e.key === 'Enter') {
      handleSaveRename(id);
    } else if (e.key === 'Escape') {
      setEditingSessionId(null);
    }
  };

  return (
    <>
      {/* Sleek Floating Tab/Button on the far-left edge when Sidebar is collapsed */}
      {!isOpen && (
        <button
          className={styles.collapsedTab}
          onClick={onToggle}
          aria-label="Open sidebar"
          title="Open chat history"
        >
          <ChevronRight size={18} />
        </button>
      )}

      {/* Backdrop overlay for mobile */}
      {isOpen && (
        <div className={styles.backdrop} onClick={onToggle} />
      )}

      {/* Main Sidebar Wrapper */}
      <aside className={`${styles.sidebar} ${isOpen ? styles.open : styles.closed}`}>
        {/* Sidebar Header */}
        <div className={styles.sidebarHeader}>
          <div className={styles.headerTitle}>
            <MessageSquare size={18} className={styles.titleIcon} />
            <h2>Conversations</h2>
          </div>
          {/* Inner Close Button on the top-right of the sidebar */}
          <button
            className={styles.closeBtn}
            onClick={onToggle}
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <ChevronLeft size={18} />
          </button>
        </div>

        {/* Action button to create a new session */}
        <button className={styles.newChatBtn} onClick={onCreateSession}>
          <Plus size={16} />
          <span>New Dialogue</span>
        </button>

        {/* List of chat sessions */}
        <div className={styles.sessionList}>
          {sessions.length === 0 ? (
            <p className={styles.emptyText}>No active dialogue channels.</p>
          ) : (
            sessions.map(s => {
              const isActive = s.id === activeSessionId;
              const isEditing = s.id === editingSessionId;
              const isDeleting = s.id === deletingSessionId;

              if (isDeleting) {
                return (
                  <div
                    key={s.id}
                    className={`${styles.sessionItem} ${styles.deleting} ${isActive ? styles.active : ''}`}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className={styles.sessionMain}>
                      <span className={styles.confirmText}>Purge?</span>
                    </div>
                    <div className={styles.sessionActions}>
                      <button
                        className={styles.actionBtn}
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteSession(s.id);
                          setDeletingSessionId(null);
                        }}
                        title="Yes, purge"
                      >
                        <Check size={14} className={styles.saveIcon} />
                      </button>
                      <button
                        className={styles.actionBtn}
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeletingSessionId(null);
                        }}
                        title="No, cancel"
                      >
                        <span style={{ fontSize: '10px', fontWeight: 'bold', color: 'var(--text-muted)' }}>✕</span>
                      </button>
                    </div>
                  </div>
                );
              }

              return (
                <div
                  key={s.id}
                  className={`${styles.sessionItem} ${isActive ? styles.active : ''}`}
                  onClick={() => !isEditing && onSelectSession(s.id)}
                >
                  <div className={styles.sessionMain}>
                    {isEditing ? (
                      <input
                        className={styles.renameInput}
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onBlur={() => handleSaveRename(s.id)}
                        onKeyDown={(e) => handleKeyDown(e, s.id)}
                        autoFocus
                        onClick={(e) => e.stopPropagation()}
                      />
                    ) : (
                      <span
                        className={styles.sessionTitle}
                        onDoubleClick={() => handleStartRename(s)}
                      >
                        {s.title}
                      </span>
                    )}
                  </div>

                  <div className={styles.sessionActions}>
                    {isEditing ? (
                      <button
                        className={styles.actionBtn}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSaveRename(s.id);
                        }}
                      >
                        <Check size={14} className={styles.saveIcon} />
                      </button>
                    ) : (
                      <>
                        <button
                          className={styles.actionBtn}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleStartRename(s);
                          }}
                          title="Rename channel"
                        >
                          <Edit3 size={14} />
                        </button>
                        <button
                          className={styles.actionBtn}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleExportSession(s.id);
                          }}
                          title="Export transcript"
                        >
                          <Download size={14} />
                        </button>
                        <button
                          className={styles.actionBtn}
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeletingSessionId(s.id);
                          }}
                          title="Purge session"
                        >
                          <Trash size={14} className={styles.deleteIcon} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Active Session Linked Documents (PDFs) */}
        {isOpen && activeSessionId && activeSessionFiles.length > 0 && (
          <div className={styles.filesSection}>
            <h3>Ingested Documents</h3>
            <div className={styles.filesList}>
              {activeSessionFiles.map((file, i) => (
                <div key={i} className={styles.fileItem} title={file}>
                  <span className={styles.fileDot}></span>
                  <span className={styles.fileName}>{file}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </aside>
    </>
  );
}
