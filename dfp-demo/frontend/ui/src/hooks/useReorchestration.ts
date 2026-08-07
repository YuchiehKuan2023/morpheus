import { useCallback, useEffect, useRef, useState } from 'react';
import type { SimProcessEntry, SimulationSession } from '@/types';
import { API } from '@/constants';
import { api } from '@/services/api';

export type ReorchestrationStatus = 'idle' | 'starting' | 'running' | 'complete' | 'failed';

interface ReorchestrationState {
  status: ReorchestrationStatus;
  stagesLog: SimProcessEntry[];
  error: string | null;
  forAnomalyId: string | null;
}

export default function useReorchestration(anomalyId: string | null, onComplete?: () => void) {
  const [state, setState] = useState<ReorchestrationState>({
    status: 'idle',
    stagesLog: [],
    error: null,
    forAnomalyId: null,
  });
  const esRef = useRef<EventSource | null>(null);

  // Load historical pipeline data when anomalyId changes
  useEffect(() => {
    if (!anomalyId) return;
    let cancelled = false;
    api
      .getAnomalyPipeline(anomalyId)
      .then((data) => {
        if (!cancelled && data.stages_log.length > 0) {
          setState((s) =>
            s.status === 'idle' ? { ...s, stagesLog: data.stages_log, forAnomalyId: anomalyId } : s
          );
        }
      })
      .catch(() => {
        /* non-critical */
      });
    return () => {
      cancelled = true;
    };
  }, [anomalyId]);

  // Clean up SSE on unmount or anomalyId change
  useEffect(() => {
    return () => {
      esRef.current?.close();
      esRef.current = null;
    };
  }, [anomalyId]);

  const trigger = useCallback(async () => {
    if (!anomalyId) return;

    setState({ status: 'starting', stagesLog: [], error: null, forAnomalyId: anomalyId });

    try {
      const { session_id } = await api.reorchestrateAnomaly(anomalyId);

      setState((s) => ({ ...s, status: 'running' }));

      // Open SSE stream for real-time stage updates
      esRef.current?.close();
      const url = API.anomalies.reorchestrateStream(anomalyId, session_id);
      const es = new EventSource(url, { withCredentials: true });
      esRef.current = es;

      es.addEventListener('session_update', (e) => {
        const session = JSON.parse(e.data) as SimulationSession;
        setState((prev) => ({
          ...prev,
          stagesLog: session.stages_log ?? prev.stagesLog,
        }));
      });

      es.addEventListener('reorchestrate_complete', (e) => {
        const session = JSON.parse(e.data) as SimulationSession;
        const finalStatus = session.stage === 'complete' ? 'complete' : 'failed';
        setState((prev) => ({
          ...prev,
          status: finalStatus,
          stagesLog: session.stages_log ?? prev.stagesLog,
        }));
        es.close();
        esRef.current = null;
        if (finalStatus === 'complete') onComplete?.();
      });

      es.onerror = () => {
        setState((prev) => ({
          ...prev,
          status: 'failed',
          error: 'Connection lost',
        }));
        es.close();
        esRef.current = null;
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to start re-orchestration';
      setState({ status: 'failed', stagesLog: [], error: msg, forAnomalyId: anomalyId });
    }
  }, [anomalyId, onComplete]);

  // Only expose data if it belongs to the current anomalyId
  const isCurrent = state.forAnomalyId === anomalyId;
  return {
    status: isCurrent ? state.status : 'idle',
    stagesLog: isCurrent ? state.stagesLog : [],
    error: isCurrent ? state.error : null,
    trigger,
  };
}
