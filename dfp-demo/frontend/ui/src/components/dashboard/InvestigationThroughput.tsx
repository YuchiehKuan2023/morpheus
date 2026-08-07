import { type FC, type ReactNode, useState } from 'react';
import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { InvestigationTrendDay } from '@/types';
import { cn, fmtConf, fmtDay, fmtHours, fmtPct } from '@/utils';
import KPICard, { type KeyPerformanceIndicator } from '../common/KPI';
import GridCols from '../common/GridCols';
import { Badge, ChartTooltip } from '..';

interface Props {
  data: InvestigationTrendDay[];
  className?: string;
}

type View = 'volume' | 'rate' | 'confidence';

const VIEW_LABELS: Record<View, string> = {
  volume: 'Volume',
  rate: 'Completion %',
  confidence: 'AI Confidence',
};

// ── Custom tooltip ─────────────────────────────────────────────────────────

interface TooltipPayload {
  active?: boolean;
  payload?: Array<{ payload: InvestigationTrendDay }>;
  label?: string;
}

const CustomTooltip: FC<TooltipPayload & { view: View }> = ({ active, payload, label, view }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  const title = fmtDay(label as string);

  let rows: { label: string; value: string }[];
  if (view === 'volume') {
    rows = [
      { label: 'Completed', value: String(d.completed) },
      { label: 'Failed', value: String(d.failed) },
      { label: 'Pending', value: String(d.pending) },
      { label: 'Triggered', value: String(d.triggered) },
      ...(d.completion_rate != null ? [{ label: 'Rate', value: fmtPct(d.completion_rate) }] : []),
      ...(d.avg_duration_hours != null
        ? [{ label: 'Avg duration', value: fmtHours(d.avg_duration_hours) }]
        : []),
    ];
  } else if (view === 'rate') {
    rows = [
      { label: 'Completion rate', value: fmtPct(d.completion_rate) },
      { label: 'Triggered', value: String(d.triggered) },
      { label: 'Avg duration', value: fmtHours(d.avg_duration_hours) },
    ];
  } else {
    rows = [
      { label: 'Avg confidence', value: fmtConf(d.avg_confidence) },
      { label: 'Triggered', value: String(d.triggered) },
      { label: 'Completed', value: String(d.completed) },
    ];
  }

  return <ChartTooltip title={title} rows={rows} variant="dark" />;
};

// ── Summary stat pills ────────────────────────────────────────────────────

const Stat: FC<{ label: ReactNode; value: ReactNode }> = ({ label, value }) => {
  const props: KeyPerformanceIndicator = {
    title: label,
    value,
    size: 'xs',
    className: 'no-border no-shadow',
  };

  return <KPICard {...props} />;
};

// ── Main component ────────────────────────────────────────────────────────

const InvestigationThroughput: FC<Props> = ({ data, className }) => {
  const [view, setView] = useState<View>('volume');

  // Aggregate summary stats from all days
  const totalTriggered = data.reduce((s, d) => s + d.triggered, 0);
  const totalCompleted = data.reduce((s, d) => s + d.completed, 0);
  const totalFailed = data.reduce((s, d) => s + d.failed, 0);
  const overallRate = totalTriggered > 0 ? (totalCompleted / totalTriggered) * 100 : null;
  const daysWithConf = data.filter((d) => d.avg_confidence != null);
  const avgConf =
    daysWithConf.length > 0
      ? daysWithConf.reduce((s, d) => s + d.avg_confidence!, 0) / daysWithConf.length
      : null;
  const daysWithDur = data.filter((d) => d.avg_duration_hours != null);
  const avgDur =
    daysWithDur.length > 0
      ? daysWithDur.reduce((s, d) => s + d.avg_duration_hours!, 0) / daysWithDur.length
      : null;

  if (data.length === 0) {
    return (
      <div className={cn('investigation-throughput', className)}>
        <p className="text-sm text-muted-foreground text-center py-8">
          No investigation data for the last 30 days.
        </p>
      </div>
    );
  }

  return (
    <div className={cn('investigation-throughput', className)}>
      {/* Summary pills */}
      <GridCols cols={6} className="mb-6">
        <Stat
          label="Triggered"
          value={<Badge variant="lime">{totalTriggered.toLocaleString()}</Badge>}
        />
        <Stat
          label="Completed"
          value={<Badge variant="lime">{totalCompleted.toLocaleString()}</Badge>}
        />
        <Stat label="Failed" value={<Badge variant="lime">{totalFailed.toLocaleString()}</Badge>} />
        <Stat
          label="Completion"
          value={
            <Badge variant="lime">{overallRate != null ? `${overallRate.toFixed(1)}%` : '—'}</Badge>
          }
        />
        <Stat
          label="Confidence"
          value={
            <Badge variant="lime">{avgConf != null ? `${(avgConf * 100).toFixed(1)}%` : '—'}</Badge>
          }
        />
        <Stat label="Avg duration" value={<Badge variant="lime">{fmtHours(avgDur)}</Badge>} />
      </GridCols>

      {/* View toggle */}
      <div className="investigation-throughput__toggle">
        {(Object.keys(VIEW_LABELS) as View[]).map((v) => (
          <button
            key={v}
            className={cn(
              'investigation-throughput__toggle-btn',
              view === v && 'investigation-throughput__toggle-btn--active'
            )}
            onClick={() => setView(v)}
          >
            {VIEW_LABELS[v]}
          </button>
        ))}
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={200} className="outline-none!">
        <ComposedChart
          data={data}
          margin={{ top: 4, right: 8, left: -30, bottom: -15 }}
          className="outline-none!"
        >
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grey-300)" className="outline-none!" />
          <XAxis
            dataKey="day"
            tickFormatter={(v: string) =>
              new Date(v).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
            }
            tick={{ fontSize: 10, fill: 'var(--muted-foreground, #94a3b8)' }}
            tickLine={false}
            axisLine={{ stroke: 'var(--grey-300)', strokeWidth: 1 }}
            interval="preserveStartEnd"
            className="outline-none!"
          />
          <YAxis
            tick={{ fontSize: 10, fill: 'var(--muted-foreground, #94a3b8)' }}
            tickLine={false}
            axisLine={{ stroke: 'var(--grey-300)', strokeWidth: 0 }}
            tickFormatter={
              view === 'rate'
                ? (v: number) => `${v}%`
                : view === 'confidence'
                  ? (v: number) => `${(v * 100).toFixed(0)}%`
                  : undefined
            }
            className="outline-none!"
          />
          <Tooltip content={<CustomTooltip view={view} />} />

          {view === 'volume' && (
            <>
              <Bar
                dataKey="completed"
                stackId="a"
                fill="#e1f2ae"
                radius={[0, 0, 0, 0]}
                maxBarSize={20}
              />
              <Bar
                dataKey="pending"
                stackId="a"
                fill="#e1f2ae"
                radius={[0, 0, 0, 0]}
                maxBarSize={20}
              />
              <Bar
                dataKey="failed"
                stackId="a"
                fill="#e1f2ae"
                radius={[2, 2, 0, 0]}
                maxBarSize={20}
              />
              <Line
                type="monotone"
                dataKey="triggered"
                stroke="#9db821"
                strokeWidth={1.5}
                dot
                activeDot={{ r: 3 }}
              />
            </>
          )}

          {view === 'rate' && (
            <Line
              type="monotone"
              dataKey="completion_rate"
              stroke="#9db821"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: '#c7f333' }}
            />
          )}

          {view === 'confidence' && (
            <Line
              type="monotone"
              dataKey="avg_confidence"
              stroke="#9db821"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, fill: '#c7f333' }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};

export default InvestigationThroughput;
