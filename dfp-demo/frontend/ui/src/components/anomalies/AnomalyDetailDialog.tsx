import { type FC, useCallback, useEffect, useReducer, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, Skeleton } from '@/components/ui';
import { TabsContent } from '@radix-ui/react-tabs';
import type { DetailAction, DetailState, SimStage } from '@/types';
import { api } from '@/services/api';
import { AnalystCard } from './widgets';
import {
  DetectionTab,
  AiAnalysisTab,
  InvestigationTab,
  RawDataTab,
  ExplanationTab,
  explainReducer,
  ReviewTab,
} from './tabs';
import { toTitleCase } from '@/utils';
import { DialogDescription } from '@radix-ui/react-dialog';
import { Shuffle, Play, CheckCircle2, XCircle } from 'lucide-react';
import { ANOMALY_DETAILS_TABS } from '@/constants';
import { useReorchestration } from '@/hooks';
import { PillTabs, Badge, UserDetails, Spinner } from '@/components';
import { fromDetail, Summary, ProcessList } from '@/components/simulation';

interface Props {
  anomalyId: string | null;
  open: boolean;
  onClose: () => void;
  /** Simulation pipeline stage — explanation tab is only active when 'complete' */
  stage?: SimStage | null;
}

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

function LoadingSkeleton() {
  return (
    <div className="space-y-4 pt-2">
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-20 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-4 w-1/4 mt-4" />
      <Skeleton className="h-24 rounded-2xl" />
      <Skeleton className="h-20 rounded-2xl" />
      <Skeleton className="h-28 rounded-2xl" />
    </div>
  );
}

export const AnomalyDetailDialog: FC<Props> = ({ anomalyId, open, onClose, stage }) => {
  const [tabState, setTabState] = useState<{ id: string | null; tab: string }>({
    id: null,
    tab: 'detection',
  });
  const activeTab = tabState.id === anomalyId ? tabState.tab : 'detection';
  const setActiveTab = (tab: string) => setTabState({ id: anomalyId, tab });
  const [state, dispatch] = useReducer(detailReducer, { status: 'idle' });
  const [explainState, dispatchExplain] = useReducer(explainReducer, { status: 'idle' });
  const [fetchKey, setFetchKey] = useState(0);
  const refreshDetail = useCallback(() => setFetchKey((k) => k + 1), []);
  const reorch = useReorchestration(anomalyId, refreshDetail);

  useEffect(() => {
    if (!open || !anomalyId) return;
    dispatch({ type: 'fetch' });
    let cancelled = false;

    api
      .getAnomalyDetail(anomalyId)
      .then((data) => {
        if (!cancelled) dispatch({ type: 'success', payload: data });
      })
      .catch(() => {
        if (!cancelled) dispatch({ type: 'error' });
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
  }, [open, anomalyId, fetchKey]);

  const isLoading = state.status === 'idle' || state.status === 'loading';
  const detail = state.status === 'success' ? state.data : null;
  const investigation = detail?.investigation;
  const errorMsg = state.status === 'error' ? state.message : null;
  const shortId = anomalyId?.slice(0, 8) ?? '—';
  const user = detail?.user;
  const analyst = investigation?.assignedAnalyst;
  const canReorchestrate = detail && !detail.processed;

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent
        className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col"
        data-id="anomaly-detail-dialog"
      >
        <DialogHeader className="shrink-0">
          <div className="flex gap-2 flex-wrap flex-col">
            <DialogTitle className="text-[24px]">Anomaly Detail</DialogTitle>
            <DialogDescription className="flex items-center gap-2 flex-wrap">
              <Badge>{shortId}…</Badge>
              {detail?.severity && <Badge variant="lime">{toTitleCase(detail.severity)}</Badge>}
              {detail?.isAnomaly === true && <Badge variant="lime">True Anomaly</Badge>}
              {detail?.isAnomaly === false && <Badge variant="lime">False Positive</Badge>}
              {detail?.timestamp && (
                <Badge variant="lime">
                  {new Date(detail.timestamp).toLocaleString('en-GB', {
                    day: 'numeric',
                    month: 'short',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </Badge>
              )}
              {canReorchestrate && reorch.status === 'idle' && (
                <button
                  type="button"
                  onClick={() => {
                    setActiveTab('pipeline');
                    reorch.trigger();
                  }}
                  className="dfp-badge lime cursor-pointer hover:opacity-80 transition-opacity inline-flex items-center gap-1"
                >
                  <Play className="h-3 w-3" />
                  Run AI Analysis
                </button>
              )}
              {(reorch.status === 'starting' || reorch.status === 'running') && (
                <span className="dfp-badge inline-flex items-center gap-1.5">
                  <Spinner height={3} width={3} marginBottom={0} />
                  Processing…
                </span>
              )}
              {(reorch.status === 'complete' ||
                detail?.processed ||
                detail?.validatedBy === 'ai_auto_labeler') && (
                <span className="dfp-badge lime inline-flex items-center gap-1">
                  <CheckCircle2 className="h-3 w-3" />
                  Complete
                </span>
              )}
              {reorch.status === 'failed' && (
                <span className="dfp-badge inline-flex items-center gap-1 text-red-400">
                  <XCircle className="h-3 w-3" />
                  Failed
                </span>
              )}
            </DialogDescription>
          </div>
          {user && (
            <div className="mt-2 text-xs flex justify-center items-center w-fit mx-auto gap-2">
              {/* Anomaly user */}
              <UserDetails {...{ user }} />
              {/* Assigned analyst */}
              {analyst && (
                <>
                  <Shuffle />
                  <AnalystCard {...{ analyst }} />
                </>
              )}
            </div>
          )}
        </DialogHeader>

        {isLoading && (
          <div className="flex-1 overflow-auto px-1">
            <LoadingSkeleton />
          </div>
        )}

        {errorMsg && (
          <div className="flex-1 flex flex-col items-start justify-center gap-4 py-10">
            <p className="text-sm text-muted-foreground">{errorMsg}</p>
            <button
              type="button"
              onClick={() => setFetchKey((k) => k + 1)}
              className="inline-flex items-center rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Retry
            </button>
          </div>
        )}

        {detail && (
          <PillTabs
            tabs={ANOMALY_DETAILS_TABS}
            value={activeTab}
            onValueChange={setActiveTab}
            className="flex-1 min-h-0"
            navClassName="mt-0 mb-4"
          >
            <TabsContent
              value="detection"
              className="flex-1 mt-3 overflow-auto data-[state=inactive]:hidden pb-4"
            >
              <DetectionTab detail={detail} />
            </TabsContent>
            <TabsContent
              value="ai"
              className="flex-1 mt-3 overflow-auto data-[state=inactive]:hidden pb-4"
            >
              <AiAnalysisTab llm={detail.llmExplanation} />
            </TabsContent>
            <TabsContent
              value="investigation"
              className="flex-1 mt-3 overflow-auto data-[state=inactive]:hidden pb-4"
            >
              <InvestigationTab investigation={detail.investigation} />
            </TabsContent>
            <TabsContent
              value="explanation"
              className="flex-1 mt-3 overflow-auto data-[state=inactive]:hidden pb-4"
            >
              <ExplanationTab
                detail={detail}
                explain={explainState}
                locked={stage != null && stage !== 'complete'}
              />
            </TabsContent>
            <TabsContent
              value="pipeline"
              className="flex-1 mt-3 overflow-auto data-[state=inactive]:hidden pb-4"
            >
              {reorch.stagesLog.length > 0 ? (
                <>
                  <ProcessList
                    stagesLog={reorch.stagesLog}
                    isClean={false}
                    anomalyId={anomalyId ?? undefined}
                  />
                  {anomalyId && <Summary data={fromDetail(detail)} />}
                </>
              ) : (
                <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
                  <Play className="h-10 w-10 opacity-30" />
                  <p className="text-sm font-medium">No pipeline run yet</p>
                  <p className="text-xs text-center max-w-xs leading-relaxed">
                    {canReorchestrate
                      ? 'Click "Run AI Analysis" to process this anomaly through the full AI pipeline.'
                      : 'This anomaly has already been processed by the AI pipeline.'}
                  </p>
                </div>
              )}
            </TabsContent>
            <TabsContent
              value="raw"
              className="flex-1 mt-3 overflow-auto data-[state=inactive]:hidden pb-4"
            >
              <RawDataTab
                originalEvent={detail.originalEvent}
                aiEnrichment={detail.aiEnrichment}
                rawDetection={detail.rawDetection}
              />
            </TabsContent>
            <TabsContent
              value="review"
              className="flex-1 mt-3 overflow-auto data-[state=inactive]:hidden pb-4"
            >
              <ReviewTab detail={detail} onRefresh={() => setFetchKey((k) => k + 1)} />
            </TabsContent>
          </PillTabs>
        )}
      </DialogContent>
    </Dialog>
  );
};
