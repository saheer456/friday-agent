import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import styles from './ErrorBoundary.module.css';

interface Props {
  children?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className={styles.errorContainer}>
          <div className={styles.errorBox}>
            <div className={styles.icon}>⚠️</div>
            <h2>System Fault</h2>
            <p className={styles.sub}>A critical error occurred in the UI layer.</p>
            <div className={styles.trace}>
              {this.state.error?.toString()}
            </div>
            <button className={styles.btn} onClick={() => window.location.reload()}>
              Reboot System
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
