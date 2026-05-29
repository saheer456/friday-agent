import { Zap } from 'lucide-react';
import styles from './GreetingSuggestions.module.css';

interface GreetingSuggestionsProps {
  suggestions: string[];
  onSelect: (text: string) => void;
}

export function GreetingSuggestions({ suggestions, onSelect }: GreetingSuggestionsProps) {
  if (!suggestions || suggestions.length === 0) return null;

  return (
    <div className={styles.wrap}>
      {suggestions.map((s, i) => (
        <button
          key={i}
          className={styles.chip}
          onClick={() => onSelect(s)}
          title={s}
        >
          <Zap size={12} className={styles.chipIcon} />
          <span>{s}</span>
        </button>
      ))}
    </div>
  );
}
