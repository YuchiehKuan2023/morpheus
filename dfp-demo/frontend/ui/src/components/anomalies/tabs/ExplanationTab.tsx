/* eslint-disable react-refresh/only-export-components */
/**
 * ExplanationTab — shared tab content for anomaly explainability.
 *
 * Renders:
 *  - KPI row: Confidence %, Risk Score, Anomaly Score, Mean |Z|
 *  - SHAPChart (top drivers + mitigators from pre-computed SHAP)
 *  - LIME local explanation weights
 *
 * Used by both:
 *  - components/anomalies/AnomalyDetailSheet   (Anomalies page)
 *  - components/simulation/AnomalyDetailDialog  (Simulation page)
 */
import { AlertTriangle, Lock } from 'lucide-react';
import { Skeleton } from '@/components/ui';
import { Badge, DialogSection, GridCols, KPICard } from '@/components';
import { SHAPChart } from '../widgets/SHAPChart';
import type { AnomalyDetail, AnomalyExplanation } from '@/types';

// ── Exported state types ──────────────────────────────────────────────────────

export type ExplainState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: AnomalyExplanation }
  | { status: 'error' };

export type ExplainAction =
  | { type: 'fetch' }
  | { type: 'success'; payload: AnomalyExplanation }
  | { type: 'error' };

export function explainReducer(_state: ExplainState, action: ExplainAction): ExplainState {
  switch (action.type) {
    case 'fetch':
      return { status: 'loading' };
    case 'success':
      return { status: 'success', data: action.payload };
    case 'error':
      return { status: 'error' };
    default:
      return _state;
  }
}

// ── Sub-components ────────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="space-y-4 pt-2">
      <div className="grid grid-cols-4 gap-3">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-20 rounded-2xl" />
        ))}
      </div>
      <Skeleton className="h-4 w-1/4 mt-4" />
      <Skeleton className="h-40 rounded-2xl" />
      <Skeleton className="h-4 w-1/4 mt-2" />
      <Skeleton className="h-32 rounded-2xl" />
    </div>
  );
}

function LimeRows({ weights }: { weights: { label: string; weight: number; value: number }[] }) {
  const max = Math.max(...weights.map((w) => Math.abs(w.weight)), 1e-9);
  return (
    <>
      {weights.map((weight) => {
        const isPos = weight.weight >= 0;
        const pctW = `${Math.round((Math.abs(weight.weight) / max) * 100)}%`;
        return (
          <div key={weight.label} className="flex items-center gap-3 py-1">
            <span className="w-44 shrink-0 text-right text-xs text-muted-foreground leading-tight truncate">
              {weight.label}
            </span>
            <div className="flex-1 h-8 relative bg-muted/30 rounded-sm overflow-hidden">
              <div
                className="h-full rounded-sm"
                style={{
                  width: pctW,
                  background: isPos ? 'var(--brand-dark-lime)' : 'var(--brand-pale-lime)',
                  opacity: 0.8,
                }}
              />
            </div>
            <span className="w-16 shrink-0 text-right text-xs font-mono text-black">
              {isPos ? '+' : ''}
              {weight.weight.toFixed(3)}
            </span>
          </div>
        );
      })}
    </>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

interface Props {
  detail: AnomalyDetail;
  explain: ExplainState;
  /**
   * When `locked` is true an overlay is shown until agent orchestration
   * is complete.
   */
  locked?: boolean;
}

export function ExplanationTab({ detail, explain, locked = false }: Props) {
  if (locked) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
        <Lock className="h-10 w-10 opacity-30" />
        <p className="text-sm font-medium">Explanation unavailable</p>
        <p className="text-xs text-center max-w-xs leading-relaxed">
          The full explainability report is generated after the agent orchestrator completes its
          analysis. Check back once the pipeline reaches{' '}
          <span className="font-semibold text-foreground">Complete</span>.
        </p>
      </div>
    );
  }

  if (explain.status === 'loading') return <LoadingSkeleton />;

  if (explain.status === 'error') {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-2 text-muted-foreground">
        <AlertTriangle className="h-8 w-8 opacity-50" />
        <p className="text-sm">Could not load explanation data.</p>
      </div>
    );
  }

  const ex = explain.status === 'success' ? explain.data : null;
  const hasShap = (ex?.shap?.topDrivers.length ?? 0) + (ex?.shap?.topMitigators.length ?? 0) > 0;
  const hasConf = ex?.confidence != null;
  const hasLime = (ex?.lime?.limeWeights.length ?? 0) > 0;

  const confPct = hasConf ? `${Math.round(ex!.confidence!.confidence * 100)}%` : '—';
  const riskVal = detail.riskScore != null ? Math.round(detail.riskScore) : '—';
  const anomalyVal = detail.anomalyScore.toFixed(2);
  const zVal = detail.meanAbsZ != null ? detail.meanAbsZ.toFixed(2) : '—';

  return (
    <div className="space-y-4 pl-1 pr-1">
      {/* KPI row */}
      <GridCols cols={4}>
        <KPICard
          title="Confidence"
          value={<Badge>{confPct}</Badge>}
          subtitle={
            hasConf
              ? ex!.confidence!.confidence >= 0.7
                ? 'High reliability'
                : 'Low reliability'
              : undefined
          }
          size="sm"
          className="no-border no-shadow"
        />
        <KPICard
          title="Risk Score"
          value={<Badge>{riskVal}</Badge>}
          subtitle="out of 100"
          size="sm"
          className="no-border no-shadow"
        />
        <KPICard
          title="Anomaly Score"
          value={<Badge>{anomalyVal}</Badge>}
          subtitle="DFP signal"
          size="sm"
          className="no-border no-shadow"
        />
        <KPICard
          title="Mean |Z|"
          value={<Badge>{zVal}</Badge>}
          subtitle="std. deviations"
          size="sm"
          className="no-border no-shadow"
        />
      </GridCols>

      {/* Confidence component breakdown */}
      {hasConf && (
        <>
          <div className="separator" />
          <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
            <span className="shrink-0">Confidence breakdown:</span>
            <span className="inline-flex items-center gap-1">
              <Badge variant="lime">
                Risk {Math.round(ex!.confidence!.components.risk * 100)}%
              </Badge>
            </span>
            <span className="inline-flex items-center gap-1">
              <Badge variant="lime">DFP {Math.round(ex!.confidence!.components.dfp * 100)}%</Badge>
            </span>
            <span className="inline-flex items-center gap-1">
              <Badge variant="lime">LLM {Math.round(ex!.confidence!.components.llm * 100)}%</Badge>
            </span>
          </div>
          <div className="separator" />
        </>
      )}

      {/* SHAP feature attribution */}
      {hasShap && (
        <DialogSection
          title="SHAP Feature Attribution"
          actions={
            <>
              <Badge>{ex!.shap!.topDrivers.length} drivers</Badge>
              <Badge>{ex!.shap!.topMitigators.length} mitigators</Badge>
              {ex!.shap!.shapUsed && <Badge variant="lime">SHAP</Badge>}
            </>
          }
          description={
            <SHAPChart topDrivers={ex!.shap!.topDrivers} topMitigators={ex!.shap!.topMitigators} />
          }
        />
      )}

      {/* LIME local explanation */}
      {hasLime && (
        <DialogSection
          title="LIME Local Explanation"
          actions={
            <>
              <Badge>{ex!.lime!.limeWeights.length} features</Badge>
              <Badge variant="lime">on-demand</Badge>
            </>
          }
          description={
            <div className="space-y-1 pt-1">
              <LimeRows weights={ex!.lime!.limeWeights} />
            </div>
          }
        />
      )}

      {/* Nothing to show */}
      {!hasShap && !hasLime && explain.status === 'success' && (
        <DialogSection
          title="No Explanation Data"
          description="SHAP and LIME data are not yet available for this anomaly. This anomaly may have been processed before the explainability pipeline was enabled."
        />
      )}
    </div>
  );
}
