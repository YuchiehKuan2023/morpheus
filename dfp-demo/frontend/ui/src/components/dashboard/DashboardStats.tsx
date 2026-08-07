import type { FC } from 'react';
import { GridCols, KPICard, TrendBadge } from '..';
import type { Stats, StatsTrend } from '@/types';
import { STATS } from '@/constants';

interface Props {
  stats: Stats | null;
  trend: StatsTrend | null;
}

const interpolate = (
  cfg: (typeof STATS)[keyof typeof STATS],
  vars: Record<string, string | number>
) => {
  const { subtitle } = cfg;
  if (typeof subtitle !== 'string') return cfg;
  return {
    ...cfg,
    subtitle: subtitle.replace(/\{(\w+)\}/g, (_, key) => String(vars[key] ?? `{${key}}`)),
  };
};

const DashboardStats: FC<Props> = ({ stats, trend }) => {
  if (!stats) return null;

  const {
    totalEvents,
    totalAnomalies,
    anomalies: { critical, high, medium, low },
    avgAnomalyScore,
    totalUsers,
    activeUsers,
  } = stats;

  // totalEvents from the API already includes both training/normal and anomalous
  // events, so do not add totalAnomalies again here.
  const eventsTotal = totalEvents ?? 0;
  const averageScore = avgAnomalyScore != null ? avgAnomalyScore.toFixed(2) : '—';

  return (
    <div className="dashboard-stats">
      <GridCols cols={4}>
        <KPICard
          value={critical ?? '—'}
          {...{ ...STATS.critical }}
          icons={trend?.critical ? [<TrendBadge trend={trend.critical} />] : undefined}
        />
        <KPICard
          value={high ?? '—'}
          {...{ ...STATS.high }}
          icons={trend?.high ? [<TrendBadge trend={trend.high} />] : undefined}
        />
        <KPICard
          value={medium ?? '—'}
          {...{ ...STATS.medium }}
          icons={trend?.medium ? [<TrendBadge trend={trend.medium} />] : undefined}
        />
        <KPICard
          value={low ?? '—'}
          {...{ ...STATS.low }}
          icons={trend?.low ? [<TrendBadge trend={trend.low} />] : undefined}
        />
      </GridCols>

      <GridCols cols={5} className="mt-6">
        <KPICard value={eventsTotal ?? '—'} {...{ ...STATS.totalEvents }} />
        <KPICard
          value={totalAnomalies ?? '—'}
          {...interpolate(STATS.totalAnomalies, { N: activeUsers })}
        />
        <KPICard value={averageScore} {...{ ...STATS.avgAnomalyScore }} />
        <KPICard value={totalUsers ?? '—'} {...{ ...STATS.totalUsers }} />
        <KPICard value={activeUsers ?? '—'} {...{ ...STATS.activeUsers }} />
      </GridCols>
    </div>
  );
};

export default DashboardStats;
