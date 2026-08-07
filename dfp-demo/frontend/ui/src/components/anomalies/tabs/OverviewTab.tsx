import { GlassCard, KPICard, UserDetails } from '@/components';
import type { AnomalyDetail } from '@/types';

// ── Helpers ──────────────────────────────────────────────────────────────────

function Row({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <>
      <dt className="text-white/40">{label}</dt>
      <dd className="text-white/80 font-medium">{value ?? '–'}</dd>
    </>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

interface Props {
  detail: AnomalyDetail;
}

export function OverviewTab({ detail }: Props) {
  return (
    <div className="space-y-4">
      {/* KPI row */}
      <div className="grid grid-cols-3 gap-3">
        <KPICard
          title="Risk Score"
          value={detail.riskScore != null ? Math.round(detail.riskScore) : '–'}
          subtitle="out of 100"
          size="sm"
        />
        <KPICard
          title="Anomaly Score"
          value={detail.anomalyScore.toFixed(2)}
          subtitle="DFP signal"
          size="sm"
        />
        <KPICard title="Severity" value={detail.severity ?? '-'} size="sm" />
      </div>

      {/* User */}
      {detail.user && (
        <GlassCard title="User">
          <UserDetails user={detail.user} />
        </GlassCard>
      )}

      {/* Root cause / classification */}
      <GlassCard title="Classification">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <Row label="Root Cause" value={detail.rootCause} />
          <Row label="Sub-Category" value={detail.subCategory} />
          <Row label="Classified By" value={detail.classifiedBy} />
          <Row label="Status" value={detail.status} />
          <Row
            label="Class. Confidence"
            value={
              detail.classificationConfidence != null
                ? `${(detail.classificationConfidence * 100).toFixed(0)}%`
                : null
            }
          />
          <Row
            label="Valid. Confidence"
            value={
              detail.validationConfidence != null
                ? `${(detail.validationConfidence * 100).toFixed(0)}%`
                : null
            }
          />
        </dl>
        {detail.validationReasoning && (
          <p className="text-xs text-white/50 mt-3 leading-relaxed">{detail.validationReasoning}</p>
        )}
      </GlassCard>

      {/* LLM narrative */}
      {detail.llmExplanation && (
        <GlassCard title="AI Analysis">
          {detail.llmExplanation.contextAnalysis && (
            <p className="text-sm text-white/70 leading-relaxed mb-3">
              {detail.llmExplanation.contextAnalysis}
            </p>
          )}
          {detail.llmExplanation.riskAssessment && (
            <div className="mb-3">
              <h5 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-1">
                Risk Assessment
              </h5>
              <p className="text-sm text-white/70 leading-relaxed">
                {detail.llmExplanation.riskAssessment}
              </p>
            </div>
          )}
          {detail.llmExplanation.recommendations && (
            <div>
              <h5 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-1">
                Recommendations
              </h5>
              <p className="text-sm text-white/70 leading-relaxed">
                {detail.llmExplanation.recommendations}
              </p>
            </div>
          )}
        </GlassCard>
      )}
    </div>
  );
}
