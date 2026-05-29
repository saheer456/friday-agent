import { useState } from 'react';
import { CheckCircle, Circle, ChevronDown, ChevronUp, Cpu } from 'lucide-react';
import styles from './PlanCard.module.css';

interface PlanStep {
  title: string;
  detail: string;
  done: boolean;
}

interface PlanCardProps {
  summary: string;
  steps: PlanStep[];
  isDone: boolean;
}

export function PlanCard({ summary, steps, isDone }: PlanCardProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className={`${styles.card} ${isDone ? styles.done : styles.active}`}>
      <button className={styles.header} onClick={() => setCollapsed(c => !c)}>
        <div className={styles.headerLeft}>
          <Cpu size={15} className={styles.icon} />
          <span className={styles.label}>Planner Engine</span>
          {!isDone && <span className={styles.activePill}>Running</span>}
          {isDone && <span className={styles.donePill}>Complete</span>}
        </div>
        <div className={styles.headerRight}>
          {summary && <span className={styles.summary}>{summary}</span>}
          {collapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </div>
      </button>

      {!collapsed && steps.length > 0 && (
        <ol className={styles.steps}>
          {steps.map((step, i) => (
            <li key={i} className={`${styles.step} ${step.done ? styles.stepDone : ''}`}>
              <span className={styles.stepIcon}>
                {step.done
                  ? <CheckCircle size={14} className={styles.checkIcon} />
                  : <Circle size={14} className={styles.circleIcon} />
                }
              </span>
              <div className={styles.stepText}>
                <span className={styles.stepTitle}>{step.title}</span>
                {step.detail && <span className={styles.stepDetail}>{step.detail}</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
