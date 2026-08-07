import { API, DEFAULT_STATUS } from '@/constants';
import { PAGE_SIZE_RUNNING, PAGE_SIZE_IDLE } from '@/constants/simulation';
import type {
  FilterTab,
  PaginatedSessions,
  SessionCounts,
  SimulationSession,
  SimulationStatus,
  SimulationUser,
  SimSpeed,
} from '@/types';
import { useCallback, useEffect, useRef, useState } from 'react';
import { store } from '@/store';
import { setSimulationRunning } from '@/features';

type SimulationStatusUpdate = Partial<SimulationStatus>;

const EMPTY_COUNTS: SessionCounts = { all: 0, anomalies: 0, clean: 0, in_progress: 0 };

interface UseSimulationReturn {
  /** Current page of sessions from the server. */
  sessions: SimulationSession[];
  /** Category counts across all sessions (not just current page). */
  counts: SessionCounts;
  /** Current page number (1-based). */
  page: number;
  /** Total pages for the current tab. */
  totalPages: number;
  /** Items per page. */
  pageSize: number;
  status: SimulationStatus;
  users: SimulationUser[];
  connected: boolean;
  /** Fetch a specific page + tab from the server. */
  fetchSessions: (page: number, tab: FilterTab) => Promise<void>;
  startSimulation: (users: string[], speed: SimSpeed) => Promise<void>;
  stopSimulation: () => Promise<void>;
}

function useSimulation(): UseSimulationReturn {
  const [sessions, setSessions] = useState<SimulationSession[]>([]);
  const [counts, setCounts] = useState<SessionCounts>(EMPTY_COUNTS);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE_IDLE);
  const [status, setStatus] = useState<SimulationStatus>(DEFAULT_STATUS);
  const [users, setUsers] = useState<SimulationUser[]>([]);
  const [connected, setConnected] = useState(false);

  const esRef = useRef<EventSource | null>(null);
  const runIdRef = useRef<string | null>(null);
  /** Track the current tab + page so SSE handlers can re-fetch the right view. */
  const activeTabRef = useRef<FilterTab>('all');
  const activePageRef = useRef(1);

  // ── Fetch sessions from server ─────────────────────────────────────────────
  const fetchSessions = useCallback(
    async (reqPage: number, tab: FilterTab) => {
      activeTabRef.current = tab;
      activePageRef.current = reqPage;
      const running = status.running;
      const ps = running ? PAGE_SIZE_RUNNING : PAGE_SIZE_IDLE;
      setPageSize(ps);

      try {
        const url = API.simulation.sessions({
          runId: running ? (runIdRef.current ?? undefined) : undefined,
          page: reqPage,
          pageSize: ps,
          tab,
        });
        const res = await fetch(url, { credentials: 'include' });
        if (!res.ok) return;
        const data: PaginatedSessions = await res.json();
        setSessions(data.items);
        setCounts(data.counts);
        setPage(data.page);
        setTotalPages(data.totalPages);
        setPageSize(data.pageSize);
      } catch {
        /* backend may not be running yet */
      }
    },
    [status.running]
  );

  /** Convenience: refetch the current view (same page + tab). */
  const refetchCurrent = useCallback(() => {
    fetchSessions(activePageRef.current, activeTabRef.current);
  }, [fetchSessions]);

  // ── Fetch available users once ─────────────────────────────────────────────
  useEffect(() => {
    fetch(API.simulation.users, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((data: SimulationUser[]) => setUsers(data))
      .catch((err) => console.error('Failed to load simulation users:', err));
  }, []);

  // ── Fetch current status + first page on mount ─────────────────────────────
  useEffect(() => {
    fetch(API.simulation.status, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((data: SimulationStatus) => {
        setStatus(data);
        if (data.run_id) {
          runIdRef.current = data.run_id;
        }
        // Fetch first page (will scope to run_id if running)
        const ps = data.running ? PAGE_SIZE_RUNNING : PAGE_SIZE_IDLE;
        const url = API.simulation.sessions({
          runId: data.running ? (data.run_id ?? undefined) : undefined,
          page: 1,
          pageSize: ps,
        });
        return fetch(url, { credentials: 'include' });
      })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: PaginatedSessions | null) => {
        if (data) {
          setSessions(data.items);
          setCounts(data.counts);
          setPage(data.page);
          setTotalPages(data.totalPages);
          setPageSize(data.pageSize);
        }
      })
      .catch(() => {
        /* backend may not be running yet */
      });
  }, []);

  // ── SSE connection ─────────────────────────────────────────────────────────
  const openStream = useCallback(
    (runId?: string | null) => {
      if (esRef.current) {
        esRef.current.close();
      }
      const url = API.simulation.stream(runId ?? undefined);
      const es = new EventSource(url);
      esRef.current = es;

      es.addEventListener('snapshot', () => {
        // On snapshot, re-fetch the current page from the server to stay in
        // sync (the snapshot replaces the full dataset).
        refetchCurrent();
        setConnected(true);
      });

      es.addEventListener('session_update', (e) => {
        const session = JSON.parse(e.data) as SimulationSession;
        // Update the session in-place if it's on the current page
        setSessions((prev) => {
          const idx = prev.findIndex((s) => s.session_id === session.session_id);
          if (idx === -1) return prev; // not on current page
          const next = [...prev];
          next[idx] = session;
          return next;
        });
        // Re-fetch counts (lightweight) — debounced by the server cache
        refetchCurrent();
      });

      es.addEventListener('status_update', (e) => {
        const s = JSON.parse(e.data) as SimulationStatusUpdate;
        setStatus((prev) => ({ ...prev, ...s }));
        if (s.run_id) runIdRef.current = s.run_id;
        if (s.running !== undefined) store.dispatch(setSimulationRunning(s.running));
      });

      es.addEventListener('run_stopped', (e) => {
        const payload = JSON.parse(e.data) as { summary: SimulationStatusUpdate };
        setStatus((prev) => ({ ...prev, ...payload.summary, running: false }));
        store.dispatch(setSimulationRunning(false));
        // Re-fetch page 1 with idle page size, unscoped (all runs)
        activePageRef.current = 1;
        fetchSessions(1, activeTabRef.current);
      });

      es.addEventListener('run_complete', (e) => {
        const payload = JSON.parse(e.data) as { summary: SimulationStatusUpdate };
        setStatus((prev) => ({ ...prev, ...payload.summary, running: false }));
        store.dispatch(setSimulationRunning(false));
        es.close();
        esRef.current = null;
        setConnected(false);
        activePageRef.current = 1;
        fetchSessions(1, activeTabRef.current);
      });

      es.onerror = () => {
        setConnected(false);
      };

      es.onopen = () => {
        setConnected(true);
      };
    },
    [fetchSessions, refetchCurrent]
  );

  // Open stream on mount and on tab visibility restore
  useEffect(() => {
    openStream(runIdRef.current);

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        const es = esRef.current;
        if (!es || es.readyState === EventSource.CLOSED) {
          openStream(runIdRef.current);
        }
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      esRef.current?.close();
    };
  }, [openStream]);

  // ── Actions ────────────────────────────────────────────────────────────────
  const startSimulation = useCallback(
    async (userIds: string[], speed: SimSpeed) => {
      const res = await fetch(API.simulation.start, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ users: userIds, speed }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = (await res.json()) as { run_id: string };
      runIdRef.current = data.run_id;
      store.dispatch(setSimulationRunning(true));
      // Reconnect SSE scoped to this run
      openStream(data.run_id);
    },
    [openStream]
  );

  const stopSimulation = useCallback(async () => {
    const res = await fetch(API.simulation.stop, {
      method: 'POST',
      credentials: 'include',
    });
    if (!res.ok) throw new Error(await res.text());
    const summary = (await res.json()) as SimulationStatus;
    setStatus((prev) => ({ ...prev, ...summary, running: false }));
    store.dispatch(setSimulationRunning(false));
  }, []);

  return {
    sessions,
    counts,
    page,
    totalPages,
    pageSize,
    status,
    users,
    connected,
    fetchSessions,
    startSimulation,
    stopSimulation,
  };
}

export default useSimulation;
