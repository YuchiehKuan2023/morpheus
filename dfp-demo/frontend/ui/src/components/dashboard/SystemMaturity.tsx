import type { FC } from 'react';
import type { SystemMaturity as SystemMaturityData } from '@/types';
import { LEVEL_SUBTITLES } from '@/constants';
import { GlassCard, InfoTooltip, KPICard, Badge } from '@/components';
import { cn } from '@/utils';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  systemMaturity: SystemMaturityData | null;
  className?: string;
}

const SystemMaturity: FC<Props> = ({ systemMaturity, className }) => {
  if (!systemMaturity)
    return <p className="text-sm text-muted-foreground py-4 text-center">No data</p>;

  const { score, level, distribution } = systemMaturity;
  const { resilient, managed, exposed } = distribution;
  const { title, description, tooltip } = DESC.anomalyIntelligence.components.systemMaturity;

  return (
    <GlassCard
      title={
        <>
          {title} <InfoTooltip content={tooltip} />
        </>
      }
      description={description}
      className={cn('system-maturity', className)}
    >
      {/* Metric boxes */}
      <div className="system-maturity__metrics">
        <KPICard
          title="MATURITY SCORE"
          value={
            <Badge className="md mb-2 inline-block" variant="lime">
              {score.toFixed(1)}
            </Badge>
          }
          subtitle="AVG MATURITY SCORE (0-100)"
          size="sm"
        />
        <KPICard
          title="MATURITY LEVEL"
          value={
            <Badge className="md mb-2 inline-block" variant="lime">
              {level}
            </Badge>
          }
          subtitle="CURRENT SECURITY POSTURE"
          size="sm"
        />
      </div>

      {/* Stacked bar */}
      <div className="system-maturity__bar-track" aria-label="Maturity distribution bar">
        {resilient.pct > 0 && (
          <div
            className="system-maturity__bar-segment system-maturity__bar-segment--resilient"
            style={{ width: `${resilient.pct}%` }}
            title={`Resilient: ${resilient.pct}%`}
          >
            {resilient.pct >= 8 && <span>{resilient.pct}%</span>}
          </div>
        )}
        {managed.pct > 0 && (
          <div
            className="system-maturity__bar-segment system-maturity__bar-segment--managed"
            style={{ width: `${managed.pct}%` }}
            title={`Managed: ${managed.pct}%`}
          >
            {managed.pct >= 8 && <span>{managed.pct}%</span>}
          </div>
        )}
        {exposed.pct > 0 && (
          <div
            className="system-maturity__bar-segment system-maturity__bar-segment--exposed"
            style={{ width: `${exposed.pct}%` }}
            title={`Exposed: ${exposed.pct}%`}
          >
            {exposed.pct >= 8 && <span>{exposed.pct}%</span>}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="system-maturity__legend">
        <span className="system-maturity__legend-item system-maturity__legend-item--resilient">
          Resilient: <strong>{resilient.count.toLocaleString()}</strong>
        </span>
        <span className="system-maturity__legend-item system-maturity__legend-item--managed">
          Managed: <strong>{managed.count.toLocaleString()}</strong>
        </span>
        <span className="system-maturity__legend-item system-maturity__legend-item--exposed">
          Exposed: <strong>{exposed.count.toLocaleString()}</strong>
        </span>
      </div>

      {/* Subtitle based on level */}
      <p className="system-maturity__subtitle">{LEVEL_SUBTITLES[level]}</p>
    </GlassCard>
  );
};

export default SystemMaturity;
