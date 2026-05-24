import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import { Copy, Check } from 'lucide-react';
import type { Message } from '../../types/api';
import { StreamMarkdown } from './StreamMarkdown';
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

  // Track if user was scrolled to bottom
  const handleScroll = () => {
    if (chatRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = chatRef.current;
      isAtBottomRef.current = scrollHeight - scrollTop - clientHeight <= 150;
    }
  };

  // Auto-scroll to bottom if user was already at bottom
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
            <p className={styles.welcomeLine}>Systems nominal, sir.</p>
            <p className={styles.welcomeSub}>I am FRIDAY, your personal assistant, created by Saheer Khan MK. Ready for input.</p>
            <div className={styles.suggestions}>
              <button 
                className={styles.suggestBtn} 
                onClick={() => onSelectSuggestion?.("Who created you?")}
              >
                Ask: "Who created you?"
              </button>
              <button 
                className={styles.suggestBtn} 
                onClick={() => onSelectSuggestion?.("What is the weather today?")}
              >
                Ask: "What is the weather today?"
              </button>
              <button 
                className={styles.suggestBtn} 
                onClick={() => onSelectSuggestion?.("Search the web for latest AI news")}
              >
                Ask: "Search the web for latest AI news"
              </button>
            </div>
          </div>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.ai}`}>
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
                    <StreamMarkdown content={m.content} />
                    <span className={styles.cursor}>▋</span>
                  </>
                ) : (
                  <ReactMarkdown rehypePlugins={[rehypeHighlight]}>
                    {m.content}
                  </ReactMarkdown>
                )}
              </div>
            </div>
          ))
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
