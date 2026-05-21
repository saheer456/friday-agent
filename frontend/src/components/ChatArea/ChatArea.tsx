import React, { useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import type { Message } from '../../types/api';
import styles from './ChatArea.module.css';

interface ChatAreaProps {
  messages: Message[];
  isSpeaking: boolean;
  onDropFile?: (file: File) => void;
}

export function ChatArea({ messages, isSpeaking, onDropFile }: ChatAreaProps) {
  const chatRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    if (chatRef.current) {
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

  return (
    <div className={styles.chatWrap}>
      <div 
        className={styles.chatScroll} 
        ref={chatRef}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {messages.length === 0 ? (
          <div className={styles.welcome}>
            <p className={styles.welcomeLine}>Systems nominal, sir.</p>
            <p className={styles.welcomeSub}>I am FRIDAY, your personal assistant, created by Saheer Khan MK. Ready for input.</p>
            <div className={styles.suggestions}>
              <button className={styles.suggestBtn} onClick={() => {
                const textarea = document.querySelector('textarea') as HTMLTextAreaElement;
                if (textarea) {
                  textarea.value = "Who created you?";
                  textarea.dispatchEvent(new Event('input', { bubbles: true }));
                  textarea.focus();
                }
              }}>
                Ask: "Who created you?"
              </button>
              <button className={styles.suggestBtn} onClick={() => {
                const textarea = document.querySelector('textarea') as HTMLTextAreaElement;
                if (textarea) {
                  textarea.value = "What is the weather today?";
                  textarea.dispatchEvent(new Event('input', { bubbles: true }));
                  textarea.focus();
                }
              }}>
                Ask: "What is the weather today?"
              </button>
              <button className={styles.suggestBtn} onClick={() => {
                const textarea = document.querySelector('textarea') as HTMLTextAreaElement;
                if (textarea) {
                  textarea.value = "Search the web for latest AI news";
                  textarea.dispatchEvent(new Event('input', { bubbles: true }));
                  textarea.focus();
                }
              }}>
                Ask: "Search the web for latest AI news"
              </button>
            </div>
          </div>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`${styles.msg} ${m.role === 'user' ? styles.user : styles.ai}`}>
              <div className={styles.msgLabel}>{m.role === 'user' ? 'YOU' : 'FRIDAY'}</div>
              <div className={styles.msgBody}>
                {m.role === 'user' ? (
                  m.content
                ) : m.streaming ? (
                  <>
                    {m.content}
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
        </div>
      )}
    </div>
  );
}
