import { useCallback, useEffect, useState } from 'react';
import { api } from '@/services/api';
import type { PlatformStats } from '@/types';
import { REFRESH_INTERVAL } from '@/constants';

export default function usePlatformStats() {
  const [platformStats, setPlatformStats] = useState<PlatformStats | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    api
      .getDashboardSnapshot()
      .then((snapshot) => setPlatformStats(snapshot.platformStats))
      .catch(() => {
        /* non-critical — cards fall back to '—' */
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [load]);

  return { platformStats, loading };
}
