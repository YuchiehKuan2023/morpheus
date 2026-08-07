import type { FC } from 'react';
import type { AnomalyInvestigation } from '@/types';
import { AgentCard, Badge, DialogSection } from '@/components';
import { Search } from 'lucide-react';

interface Props {
  investigation: AnomalyInvestigation | null;
}

export const InvestigationTab: FC<Props> = ({ investigation }) => {
  if (!investigation) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted-foreground">
        <Search className="h-10 w-10 opacity-25" />
        <p className="text-sm">No investigation found for this anomaly.</p>
      </div>
    );
  }

  const durationMs =
    investigation.triggeredAt && investigation.completedAt
      ? new Date(investigation.completedAt).getTime() -
        new Date(investigation.triggeredAt).getTime()
      : null;
  const durationLabel =
    durationMs != null
      ? durationMs < 1000
        ? `${durationMs}ms`
        : `${(durationMs / 1000).toFixed(1)}s`
      : null;

  return (
    <div className="space-y-4">
      {/* Summary */}
      <DialogSection
        title="Investigation Summary"
        actions={
          <>
            {durationLabel && <Badge>Duration: {durationLabel}</Badge>}
            {investigation.confidenceScore != null && (
              <Badge>
                Confidence:{' '}
                <span className="font-semibold text-foreground">
                  {(investigation.confidenceScore * 100).toFixed(0)}%
                </span>
              </Badge>
            )}
            <Badge
              {...(investigation.status.toLowerCase() === 'complete' ? { variant: 'lime' } : {})}
            >
              {investigation.status}
            </Badge>
          </>
        }
        description={
          <>
            {investigation.overallRecommendation && (
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
                Overall Recommendation: {investigation.overallRecommendation}
              </div>
            )}
            {investigation.agentsInvoked.length > 0 && (
              <div className="flex flex-wrap gap-1 items-center">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Agents invoked:
                </span>
                {investigation.agentsInvoked.map((a) => (
                  <Badge key={a} variant="lime">
                    {a}
                  </Badge>
                ))}
              </div>
            )}
          </>
        }
        separator
      />

      {/* Agent findings */}
      {investigation.findings.map((finding) => {
        const { agentType } = finding;

        return <AgentCard key={agentType} {...{ finding }} />;
      })}
    </div>
  );
};
