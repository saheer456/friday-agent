import React from 'react';
import styles from './ChatArea.module.css';

interface MarkdownRendererProps {
  content: string;
  isStreaming?: boolean;
}

export function MarkdownRenderer({ content, isStreaming }: MarkdownRendererProps) {
  // Parse inline elements: **bold**, *italic*, `code`, and [links](url)
  const renderInline = (text: string): React.ReactNode[] => {
    const parts: React.ReactNode[] = [];
    let key = 0;

    // Match code blocks, bold, italic, and markdown links
    const tokenRegex = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
    const subParts = text.split(tokenRegex);

    subParts.forEach((part) => {
      if (part.startsWith('`') && part.endsWith('`')) {
        parts.push(
          <code key={key++} className="inline-code" style={{
            backgroundColor: 'rgba(128, 128, 128, 0.15)',
            padding: '2px 6px',
            borderRadius: '4px',
            fontFamily: 'monospace',
            fontSize: '0.9em'
          }}>
            {part.slice(1, -1)}
          </code>
        );
      } else if (part.startsWith('**') && part.endsWith('**')) {
        parts.push(<strong key={key++} style={{ fontWeight: '600' }}>{part.slice(2, -2)}</strong>);
      } else if (part.startsWith('*') && part.endsWith('*')) {
        parts.push(<em key={key++} style={{ fontStyle: 'italic' }}>{part.slice(1, -1)}</em>);
      } else if (part.startsWith('[') && part.includes('](')) {
        const match = part.match(/\[([^\]]+)\]\(([^)]+)\)/);
        if (match) {
          parts.push(
            <a
              key={key++}
              href={match[2]}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: '#38bdf8',
                textDecoration: 'underline',
                cursor: 'pointer'
              }}
            >
              {match[1]}
            </a>
          );
        } else {
          parts.push(part);
        }
      } else {
        parts.push(part);
      }
    });

    return parts;
  };

  const parseBlocks = (text: string): React.ReactNode[] => {
    const lines = text.split('\n');
    const blocks: React.ReactNode[] = [];
    let i = 0;
    let blockKey = 0;

    while (i < lines.length) {
      const line = lines[i];

      // 1. Skip empty lines
      if (!line.trim()) {
        i++;
        continue;
      }

      // 2. Code Block
      if (line.trim().startsWith('```')) {
        const lang = line.trim().slice(3);
        const codeLines: string[] = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith('```')) {
          codeLines.push(lines[i]);
          i++;
        }
        i++; // skip closing ```
        blocks.push(
          <pre key={blockKey++} style={{
            backgroundColor: '#1e293b',
            color: '#f8fafc',
            padding: '12px 16px',
            borderRadius: '8px',
            overflowX: 'auto',
            margin: '1em 0',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            fontFamily: 'monospace',
            fontSize: '0.9em'
          }}>
            <code className={lang ? `language-${lang}` : ''}>{codeLines.join('\n')}</code>
          </pre>
        );
        continue;
      }

      // 3. Horizontal Rule
      if (line.trim() === '---' || line.trim() === '***' || line.trim() === '___') {
        blocks.push(<hr key={blockKey++} style={{ border: 'none', borderTop: '1px solid rgba(128, 128, 128, 0.2)', margin: '1.5em 0' }} />);
        i++;
        continue;
      }

      // 4. Headings
      const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
      if (headingMatch) {
        const level = headingMatch[1].length;
        const headingText = headingMatch[2];
        const headingStyle = {
          fontWeight: '600',
          margin: '1.2em 0 0.6em 0'
        };

        if (level === 1) {
          blocks.push(<h1 key={blockKey++} style={{ ...headingStyle, fontSize: '1.6em', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '0.3em' }}>{renderInline(headingText)}</h1>);
        } else if (level === 2) {
          blocks.push(<h2 key={blockKey++} style={{ ...headingStyle, fontSize: '1.4em' }}>{renderInline(headingText)}</h2>);
        } else if (level === 3) {
          blocks.push(<h3 key={blockKey++} style={{ ...headingStyle, fontSize: '1.2em' }}>{renderInline(headingText)}</h3>);
        } else {
          blocks.push(<h4 key={blockKey++} style={{ ...headingStyle, fontSize: '1.1em' }}>{renderInline(headingText)}</h4>);
        }
        i++;
        continue;
      }

      // 5. Table
      if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
        const tableLines: string[] = [];
        while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
          tableLines.push(lines[i].trim());
          i++;
        }

        if (tableLines.length >= 2) {
          // Parse header row
          const headerCells = tableLines[0]
            .split('|')
            .slice(1, -1)
            .map((c) => c.trim());

          // Skip separator row (tableLines[1])
          const dataRows = tableLines.slice(2).map((rowLine) =>
            rowLine
              .split('|')
              .slice(1, -1)
              .map((c) => c.trim())
          );

          blocks.push(
            <div key={blockKey++} className="table-container" style={{ overflowX: 'auto', margin: '1.2em 0' }}>
              <table style={{
                borderCollapse: 'collapse',
                width: '100%',
                borderRadius: '8px',
                overflow: 'hidden',
                fontSize: '0.95em',
                border: '1px solid rgba(128, 128, 128, 0.2)'
              }}>
                <thead>
                  <tr style={{
                    backgroundColor: 'rgba(128, 128, 128, 0.1)',
                    borderBottom: '2px solid rgba(128, 128, 128, 0.2)'
                  }}>
                    {headerCells.map((h, hi) => (
                      <th key={hi} style={{
                        padding: '10px 14px',
                        textAlign: 'left',
                        fontWeight: '600'
                      }}>
                        {renderInline(h)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {dataRows.map((row, ri) => (
                    <tr key={ri} style={{
                      borderBottom: '1px solid rgba(128, 128, 128, 0.15)',
                      backgroundColor: ri % 2 === 1 ? 'rgba(128, 128, 128, 0.05)' : 'transparent'
                    }}>
                      {row.map((cell, ci) => (
                        <td key={ci} style={{
                          padding: '9px 14px',
                          verticalAlign: 'top'
                        }}>
                          {cell.includes('<br>') ? (
                            cell.split('<br>').map((segment, si) => (
                              <div key={si}>{renderInline(segment.replace(/^•\s*/, ''))}</div>
                            ))
                          ) : (
                            renderInline(cell)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        continue;
      }

      // 6. Ordered List
      const orderedMatch = line.match(/^(\d+)\.\s+(.*)$/);
      if (orderedMatch) {
        const listItems: React.ReactNode[] = [];
        let listKey = 0;

        while (i < lines.length) {
          const itemMatch = lines[i].match(/^(\d+)\.\s+(.*)$/);
          if (!itemMatch) break;
          listItems.push(
            <li key={listKey++} style={{ marginBottom: '6px', listStylePosition: 'outside', marginLeft: '20px' }}>
              {renderInline(itemMatch[2])}
            </li>
          );
          i++;
        }

        blocks.push(
          <ol key={blockKey++} style={{ margin: '0.8em 0', paddingLeft: '0', listStyleType: 'decimal' }}>
            {listItems}
          </ol>
        );
        continue;
      }

      // 7. Unordered List
      const unorderedMatch = line.match(/^([-*+])\s+(.*)$/);
      if (unorderedMatch) {
        const listItems: React.ReactNode[] = [];
        let listKey = 0;

        while (i < lines.length) {
          const itemMatch = lines[i].match(/^([-*+])\s+(.*)$/);
          if (!itemMatch) break;
          listItems.push(
            <li key={listKey++} style={{ marginBottom: '6px', listStyleType: 'disc', listStylePosition: 'outside', marginLeft: '20px' }}>
              {renderInline(itemMatch[2])}
            </li>
          );
          i++;
        }

        blocks.push(
          <ul key={blockKey++} style={{ margin: '0.8em 0', paddingLeft: '0' }}>
            {listItems}
          </ul>
        );
        continue;
      }

      // 8. Plain Paragraph
      blocks.push(
        <p key={blockKey++} style={{ margin: '0.8em 0', lineHeight: '1.5' }}>
          {renderInline(line)}
        </p>
      );
      i++;
    }

    return blocks;
  };

  const appendCursorToNode = (node: React.ReactNode, cursorNode: React.ReactNode): React.ReactNode => {
    if (!node) return cursorNode;

    if (typeof node === 'string') {
      return (
        <>
          {node}
          {cursorNode}
        </>
      );
    }

    if (Array.isArray(node)) {
      if (node.length === 0) return [cursorNode];
      const lastIdx = node.length - 1;
      const updatedLast = appendCursorToNode(node[lastIdx], cursorNode);
      return [...node.slice(0, lastIdx), updatedLast];
    }

    if (React.isValidElement(node)) {
      const type = node.type;
      if (type === 'hr' || type === 'br' || type === 'img') {
        return (
          <>
            {node}
            {cursorNode}
          </>
        );
      }
      const children = (node.props as any).children;
      if (children === undefined || children === null) {
        return React.cloneElement(node as React.ReactElement, undefined, cursorNode);
      }
      const updatedChildren = appendCursorToNode(children, cursorNode);
      return React.cloneElement(node as React.ReactElement, undefined, updatedChildren);
    }

    return (
      <>
        {node}
        {cursorNode}
      </>
    );
  };

  const blocks = parseBlocks(content);
  if (isStreaming && blocks.length > 0) {
    const lastIdx = blocks.length - 1;
    const cursorNode = <span className={styles.cursor} />;
    blocks[lastIdx] = appendCursorToNode(blocks[lastIdx], cursorNode);
  }

  return <div className="markdown-renderer-body" style={{ width: '100%' }}>{blocks}</div>;
}
