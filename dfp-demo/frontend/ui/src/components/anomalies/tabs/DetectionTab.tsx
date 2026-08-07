import type { FC } from 'react';
import type { AnomalyDetail } from '@/types';
import { KPICard, GridCols, DialogSection, Badge } from '@/components';
import {
  DETECTION_KPIS as kpiProps,
  CLASSIFICATION_KPIS as classProps,
  VERDICT_CONFIG,
} from '@/constants/simulation';
import { toTitleCase } from '@/utils';

interface Props {
  detail: AnomalyDetail;
}

export const DetectionTab: FC<Props> = ({ detail }) => {
  const verdictKey =
    detail.isAnomaly === null ? 'null' : (String(detail.isAnomaly) as 'true' | 'false');
  const verdict = VERDICT_CONFIG[verdictKey];
  const score = detail.anomalyScore?.toFixed(2) ?? '—';
  const mean = detail.meanAbsZ != null ? detail.meanAbsZ.toFixed(1) : '—';
  const risk = detail.riskScore != null ? detail.riskScore.toFixed(1) : '—';
  const severity = toTitleCase(detail.severity ?? '—');
  const cause = detail.rootCause ? detail.rootCause.replace(/_/g, ' ') : '—';
  const category = detail.subCategory ? detail.subCategory.replace(/_/g, ' ') : '—';
  const classifier = detail.classifiedBy ?? '—';
  // Stage 2 classification confidence (true anomalies only).
  // Fall back to Stage 1 validation confidence for false positives.
  const rawConfidence = detail.classificationConfidence ?? detail.validationConfidence;
  const confidence = rawConfidence != null ? `${(rawConfidence * 100).toFixed(0)}%` : '—';

  return (
    <div className="space-y-4 pl-1 pr-1">
      {/* KPI row */}
      <GridCols cols={4}>
        <KPICard value={<Badge variant="lime">{score}</Badge>} {...{ ...kpiProps['score'] }} />
        <KPICard value={<Badge variant="lime">{mean}</Badge>} {...{ ...kpiProps['mean'] }} />
        <KPICard value={<Badge variant="lime">{risk}</Badge>} {...{ ...kpiProps['risk'] }} />
        <KPICard
          value={<Badge variant="lime">{severity}</Badge>}
          {...{ ...kpiProps['severity'] }}
        />
      </GridCols>

      <GridCols cols={4}>
        <KPICard value={<Badge>{classifier}</Badge>} {...{ ...classProps['classifier'] }} />
        <KPICard value={<Badge>{cause}</Badge>} {...{ ...classProps['cause'] }} />
        <KPICard value={<Badge>{category}</Badge>} {...{ ...classProps['category'] }} />
        <KPICard value={<Badge>{confidence}</Badge>} {...{ ...classProps['confidence'] }} />
      </GridCols>

      {/* Intelligence verdict */}
      <DialogSection
        title="Intelligence Verdict"
        actions={
          <>
            <Badge>{verdict.label}</Badge>
            <Badge>
              {detail.validationConfidence != null &&
                `Confidence: ${(detail.validationConfidence * 100).toFixed(0)}%`}
            </Badge>
            <Badge variant="lime">complete</Badge>
          </>
        }
        description={detail.validationReasoning ?? 'No additional reasoning provided.'}
        separator
      />
    </div>
  );
};
