import React, { useEffect, useRef, useState } from 'react';
import { Copy, Check, Loader } from 'lucide-react';
import type { Message } from '../../types/api';
import { MarkdownRenderer } from './MarkdownRenderer';
import { PlanCard } from './PlanCard';
import { GreetingSuggestions } from './GreetingSuggestions';
import { VoiceVisualizer } from './VoiceVisualizer';
import styles from './ChatArea.module.css';

interface ChatAreaProps {
  messages: Message[];
  isSpeaking: boolean;
  onDropFile?: (file: File) => void;
  onSelectSuggestion?: (text: string) => void;
  onLoadMore?: () => void;
  hasMore?: boolean;
  isLoadingHistory?: boolean;
}

function formatDateLabel(dateStr: string): string {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '';
  const now = new Date();
  const diff = now.getTime() - d.getTime();
  const days = Math.floor(diff / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return d.toLocaleDateString([], { weekday: 'long' });
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

function shouldShowDateSeparator(curr: Message, prev?: Message): boolean {
  if (!prev) return true;
  const currDate = curr.timestamp ? new Date(curr.timestamp) : null;
  const prevDate = prev.timestamp ? new Date(prev.timestamp) : null;
  if (!currDate || !prevDate) return false;
  return currDate.toDateString() !== prevDate.toDateString();
}

export function ChatArea({
  messages, isSpeaking, onDropFile, onSelectSuggestion,
  onLoadMore, hasMore, isLoadingHistory,
}: ChatAreaProps) {
  const chatRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const loadingMoreRef = useRef(false);

  const handleScroll = () => {
    if (chatRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = chatRef.current;
      isAtBottomRef.current = scrollHeight - scrollTop - clientHeight <= 150;
    }
  };

  useEffect(() => {
    if (chatRef.current && isAtBottomRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messages, isSpeaking]);

  // ── Infinite scroll via IntersectionObserver ──────────────
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !onLoadMore || !hasMore || isLoadingHistory) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !loadingMoreRef.current) {
          loadingMoreRef.current = true;
          onLoadMore();
          setTimeout(() => { loadingMoreRef.current = false; }, 500);
        }
      },
      { rootMargin: '200px 0px' },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [onLoadMore, hasMore, isLoadingHistory]);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (chatRef.current) chatRef.current.style.outline = '2px dashed rgba(167,139,250,0.5)';
  };
  const handleDragLeave = () => {
    if (chatRef.current) chatRef.current.style.outline = '';
  };
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (chatRef.current) chatRef.current.style.outline = '';
    const file = e.dataTransfer.files?.[0];
    if (file && onDropFile) onDropFile(file);
  };

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  // ── Group messages for date separators ────────────────────
  const grouped = messages.reduce<{ dateLabel: string; msgs: typeof messages }[]>((acc, m, i) => {
    const prev = i > 0 ? messages[i - 1] : undefined;
    if (shouldShowDateSeparator(m, prev)) {
      acc.push({ dateLabel: formatDateLabel(m.timestamp || ''), msgs: [m] });
    } else if (acc.length > 0) {
      acc[acc.length - 1].msgs.push(m);
    }
    return acc;
  }, []);

  return (
    <div className={styles.chatWrap}>
      <div
        className={styles.chatScroll}
        ref={chatRef}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onScroll={handleScroll}
      >
        {/* ── Sentinel for infinite scroll ── */}
        {hasMore && (
          <div ref={sentinelRef} className={styles.loadMoreSentinel}>
            {isLoadingHistory ? (
              <Loader size={18} className={styles.loadMoreSpinner} />
            ) : (
              <span className={styles.loadMoreHint}>Scroll for older messages</span>
            )}
          </div>
        )}

        {messages.length === 0 && !isLoadingHistory ? (
          <div className={styles.welcome}>
            <div className={styles.welcomeOrb} />
            <p className={styles.welcomeLine}>Ready, sir.</p>
            <p className={styles.welcomeSub}>Start a conversation or choose a channel.</p>
          </div>
        ) : (
          grouped.map((group, gi) => (
            <div key={`g-${gi}`}>
              <div className={styles.dateSeparator}>
                <span className={styles.dateLabel}>{group.dateLabel}</span>
              </div>
              {group.msgs.map((m: any) => {
                // ── PlanCard ──
                if (m.role === 'plan') {
                  return (
                    <PlanCard
                      key={m.id}
                      summary={m.content}
                      steps={m.planSteps || []}
                      isDone={!!m.planDone}
                    />
                  );
                }
                // ── Chat bubble ──
                return (
                  <React.Fragment key={m.id}>
                    <div className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.ai} ${m.streaming ? styles.streaming : ''}`}>
                      <div className={styles.msgHeader}>
                        <div className={styles.msgLabel}>{m.role === 'user' ? 'YOU' : 'FRIDAY'}</div>
                        <div className={styles.msgMeta}>
                          {m.timestamp && <span className={styles.msgTime}>{m.timestamp}</span>}
                          {m.role === 'assistant' && !m.streaming && (
                            <button className={styles.copyBtn} onClick={() => handleCopy(m.id, m.content)} title="Copy">
                              {copiedId === m.id ? <Check size={14} /> : <Copy size={14} />}
                            </button>
                          )}
                        </div>
                      </div>
                      <div className={styles.msgBody}>
                        {m.role === 'user' ? (
                          m.content
                        ) : (
                          <MarkdownRenderer content={m.content} isStreaming={m.streaming} />
                        )}
                      </div>
                    </div>
                    {m.isGreeting && !m.streaming && m.suggestions?.length > 0 && (
                      <GreetingSuggestions suggestions={m.suggestions} onSelect={(text) => onSelectSuggestion?.(text)} />
                    )}
                  </React.Fragment>
                );
              })}
            </div>
          ))
        )}

        {isLoadingHistory && messages.length > 0 && (
          <div className={styles.loadingHistory}>
            <Loader size={20} className={styles.loadMoreSpinner} />
            <span>Loading history…</span>
          </div>
        )}
      </div>

      <VoiceVisualizer isSpeaking={isSpeaking} />
    </div>
  );
}
