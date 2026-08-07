/**
 * AnomalyDetailSheet — wide Dialog displaying full anomaly details with four
 * PillTabs: Overview / Explanation / Investigation / Review.
 *
 * Data fetching:
 *   - AnomalyDetail: fetched via api.getAnomalyDetail (detail + investigation)
 *   - AnomalyExplanation: fetched via api.getAnomalyExplanation (SHAP + LIME + confidence)
 *
 * Both requests fire in parallel once `anomalyId` is set.
 */
import { useCallback, useEffect, useReducer, useState } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import { Dialog, DialogContent, Skeleton } from '@/components/ui';
import { PillTabs } from '@/components';
import { OverviewTab, ExplanationTab, explainReducer, InvestigationTab, ReviewTab } from './tabs';
import { api } from '@/services/api';
import type { DetailAction, DetailState } from '@/types';

// ── Types ────────────────────────────────────────────────────────────────────

interface Props {
  anomalyId: string | null;
  open: boolean;
  onClose: () => void;
}

// ── Reducers ─────────────────────────────────────────────────────────────────

function detailReducer(_state: DetailState, action: DetailAction): DetailState {
  switch (action.type) {
    case 'fetch':
      return { status: 'loading' };
    case 'success':
      return { status: 'success', data: action.payload };
    case 'error':
      return { status: 'error', message: 'Failed to load anomaly details.' };
  }
}

// ── Severity colours ─────────────────────────────────────────────────────────

const SEV_COLOR: Record<string, string> = {
  critical: '#f87171',
  high: '#fb923c',
  medium: '#fbbf24',
  low: '#4ade80',
};

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'explanation', label: 'Explanation' },
  { id: 'investigation', label: 'Investigation' },
  { id: 'review', label: 'Review' },
];

// ── Sub-components ────────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="space-y-4 pt-2">
      <div className="grid grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-20 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-4 w-1/3 mt-4" />
      <Skeleton className="h-24 rounded-2xl" />
      <Skeleton className="h-28 rounded-2xl" />
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function AnomalyDetailSheet({ anomalyId, open, onClose }: Props) {
  const [tab, setTab] = useState('overview');
  const [detailState, dispatchDetail] = useReducer(detailReducer, { status: 'idle' });
  const [explainState, dispatchExplain] = useReducer(explainReducer, { status: 'idle' });

  const fetchDetail = useCallback(() => {
    if (!anomalyId) return;
    dispatchDetail({ type: 'fetch' });
    api
      .getAnomalyDetail(anomalyId)
      .then((d) => dispatchDetail({ type: 'success', payload: d }))
      .catch(() => dispatchDetail({ type: 'error' }));
  }, [anomalyId]);

  useEffect(() => {
    if (!anomalyId || !open) return;
    let cancelled = false;

    // Fetch detail
    dispatchDetail({ type: 'fetch' });
    api
      .getAnomalyDetail(anomalyId)
      .then((d) => {
        if (!cancelled) dispatchDetail({ type: 'success', payload: d });
      })
      .catch(() => {
        if (!cancelled) dispatchDetail({ type: 'error' });
      });

    // Fetch explanation in parallel
    dispatchExplain({ type: 'fetch' });
    api
      .getAnomalyExplanation(anomalyId)
      .then((e) => {
        if (!cancelled) dispatchExplain({ type: 'success', payload: e });
      })
      .catch(() => {
        if (!cancelled) dispatchExplain({ type: 'error' });
      });

    return () => {
      cancelled = true;
    };
  }, [anomalyId, open]);

  // Reset tab when opening a new anomaly (handled via key prop in parent)

  const detail = detailState.status === 'success' ? detailState.data : null;
  const sevColor = SEV_COLOR[detail?.severity?.toLowerCase() ?? ''] ?? '#94a3b8';

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <DialogContent className="max-w-4xl max-h-[92vh] overflow-hidden flex flex-col p-0">
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-white/10 shrink-0">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold text-white">Anomaly Detail</h2>
            {detail && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs text-white/50 font-mono">{detail.userId}</span>
                <span className="text-white/20">·</span>
                <span className="text-xs text-white/50">
                  {new Date(detail.timestamp).toLocaleString()}
                </span>
                {detail.severity && (
                  <span className="dfp-badge capitalize" style={{ color: sevColor }}>
                    {detail.severity}
                  </span>
                )}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-white/40 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Tabs nav */}
        <div className="shrink-0 px-6 pt-4">
          <PillTabs tabs={TABS} value={tab} onValueChange={setTab} compact>
            {/* content rendered below outside PillTabs to control scroll */}
            <></>
          </PillTabs>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {detailState.status === 'loading' && <LoadingSkeleton />}
          {detailState.status === 'error' && (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-white/40">
              <AlertTriangle className="h-10 w-10" />
              <p className="text-sm">
                {(detailState as { status: 'error'; message: string }).message}
              </p>
            </div>
          )}

          {detail && (
            <>
              {tab === 'overview' && <OverviewTab detail={detail} />}
              {tab === 'explanation' && <ExplanationTab detail={detail} explain={explainState} />}
              {tab === 'investigation' && <InvestigationTab investigation={detail.investigation} />}
              {tab === 'review' && <ReviewTab detail={detail} onRefresh={fetchDetail} />}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
