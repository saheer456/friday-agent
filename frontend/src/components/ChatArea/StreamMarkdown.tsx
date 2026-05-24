import React from 'react';

interface StreamMarkdownProps {
  content: string;
}

export function StreamMarkdown({ content }: StreamMarkdownProps) {
  const parseText = (text: string) => {
    const lines = text.split('\n');
    return lines.map((line, lineIdx) => {
      const parts: React.ReactNode[] = [];
      let key = 0;

      // Match `code`, **bold**, or *italic*
      const tokenRegex = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
      const subParts = line.split(tokenRegex);

      subParts.forEach((part) => {
        if (part.startsWith('`') && part.endsWith('`')) {
          parts.push(<code key={key++} className="inline-code">{part.slice(1, -1)}</code>);
        } else if (part.startsWith('**') && part.endsWith('**')) {
          parts.push(<strong key={key++}>{part.slice(2, -2)}</strong>);
        } else if (part.startsWith('*') && part.endsWith('*')) {
          parts.push(<em key={key++}>{part.slice(1, -1)}</em>);
        } else {
          parts.push(part);
        }
      });

      return (
        <div key={lineIdx} style={{ minHeight: '1.2em' }}>
          {parts.length === 0 || (parts.length === 1 && parts[0] === '') ? '\u00A0' : parts}
        </div>
      );
    });
  };

  return <div className="stream-markdown-container">{parseText(content)}</div>;
}
