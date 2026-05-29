import React, { useEffect, useRef, useState } from 'react';
import { Copy, Check } from 'lucide-react';
import type { Message } from '../../types/api';
import { MarkdownRenderer } from './MarkdownRenderer';
import { PlanCard } from './PlanCard';
import { GreetingSuggestions } from './GreetingSuggestions';
import styles from './ChatArea.module.css';

interface ChatAreaProps {
  messages: Message[];
  isSpeaking: boolean;
  onDropFile?: (file: File) => void;
  onSelectSuggestion?: (text: string) => void;
}

export function ChatArea({ messages, isSpeaking, onDropFile, onSelectSuggestion }: ChatAreaProps) {
  const chatRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);

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
        {messages.length === 0 ? (
          <div className={styles.welcome}>
            <div className={styles.welcomeOrb} />
            <p className={styles.welcomeLine}>Initializing…</p>
          </div>
        ) : (
          messages.map((m: any) => {

            // ── PlanCard (inline planner steps) ─────────────────
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

            // ── Normal chat bubble ───────────────────────────────
            return (
              <React.Fragment key={m.id}>
                <div className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.ai}`}>
                  <div className={styles.msgHeader}>
                    <div className={styles.msgLabel}>{m.role === 'user' ? 'YOU' : 'FRIDAY'}</div>
                    <div className={styles.msgMeta}>
                      {m.timestamp && <span className={styles.msgTime}>{m.timestamp}</span>}
                      {m.role === 'assistant' && !m.streaming && (
                        <button
                          className={styles.copyBtn}
                          onClick={() => handleCopy(m.id, m.content)}
                          title="Copy message"
                        >
                          {copiedId === m.id ? <Check size={14} /> : <Copy size={14} />}
                        </button>
                      )}
                    </div>
                  </div>
                  <div className={styles.msgBody}>
                    {m.role === 'user' ? (
                      m.content
                    ) : m.streaming ? (
                      <>
                        <MarkdownRenderer content={m.content} />
                        <span className={styles.cursor}>▋</span>
                      </>
                    ) : (
                      <MarkdownRenderer content={m.content} />
                    )}
                  </div>
                </div>

                {/* Suggestion chips after greeting bubble */}
                {m.isGreeting && !m.streaming && m.suggestions?.length > 0 && (
                  <GreetingSuggestions
                    suggestions={m.suggestions}
                    onSelect={(text) => onSelectSuggestion?.(text)}
                  />
                )}
              </React.Fragment>
            );
          })
        )}
      </div>

      {isSpeaking && (
        <div className={styles.speakingIndicator}>
          <div className={styles.speakingCircle}>
            <div className={styles.speakingCircleInner}></div>
          </div>
          <span className={styles.speakingText}>FRIDAY is speaking...</span>
        </div>
      )}
    </div>
  );
}
