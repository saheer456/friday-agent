import { useState, useEffect, useCallback } from 'react';
import type { SystemInfo } from '../types/api';
import { authFetch } from '../lib/api';

export function useSystem(enabled = true) {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [error, setError] = useState<boolean>(false);

  const fetchSystem = useCallback(async () => {
    try {
      const res = await authFetch('/api/system');
      if (!res.ok) throw new Error('Failed to fetch system info');
      const data = await res.json();
      setSystem(data);
      setError(false);
    } catch (err) {
      console.error('[useSystem]', err);
      setError(true);
    }
  }, []);

  useEffect(() => {
    if (enabled) {
      fetchSystem();
    }
  }, [fetchSystem, enabled]);

  return { system, error, fetchSystem };
}
