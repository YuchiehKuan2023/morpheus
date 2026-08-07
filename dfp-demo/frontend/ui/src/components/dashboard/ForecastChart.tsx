import { type FC, useEffect, useState } from 'react';
import {
  ComposedChart,
  Area,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import type { ForecastData, ForecastHistoricalPoint, ForecastPredictionPoint } from '@/types';
import { cn, fmtDay } from '@/utils';
import { api } from '@/services/api';
import { Badge, ChartTooltip } from '..';

interface ChartPoint {
  date: string;
  count?: number;
  yhat?: number;
  yhat_lower?: number;
  yhat_upper?: number;
  band?: [number, number];
}

// ── Tooltip ──────────────────────────────────────────────────────────────────

interface TooltipPayload {
  active?: boolean;
  payload?: Array<{ payload: ChartPoint }>;
  label?: string;
}

const ForecastTooltip: FC<TooltipPayload> = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;

  const rows: { label: string; value: string }[] = [];
  if (d.count != null) rows.push({ label: 'Actual', value: String(d.count) });
  if (d.yhat != null) rows.push({ label: 'Predicted', value: String(d.yhat) });
  if (d.yhat_lower != null && d.yhat_upper != null) {
    rows.push({ label: 'Range', value: `${d.yhat_lower} – ${d.yhat_upper}` });
  }

  return <ChartTooltip title={fmtDay(label as string)} rows={rows} variant="dark" />;
};

// ── Main component ───────────────────────────────────────────────────────────

interface Props {
  className?: string;
  periods?: number;
}

const ForecastChart: FC<Props> = ({ className, periods = 30 }) => {
  const [data, setData] = useState<ForecastData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getForecast(periods)
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(result.meta?.error ?? null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load forecast');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [periods]);

  if (loading) {
    return (
      <div className={cn('forecast-chart', className)}>
        <p className="text-sm text-muted-foreground text-center py-8">Loading forecast…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className={cn('forecast-chart', className)}>
        <p className="text-sm text-muted-foreground text-center py-8">
          {error || 'No forecast data available.'}
        </p>
      </div>
    );
  }

  // Merge historical + forecast into one series
  const chartData: ChartPoint[] = [
    ...data.historical.map((h: ForecastHistoricalPoint) => ({
      date: h.date,
      count: h.count,
    })),
    ...data.forecast.map((f: ForecastPredictionPoint) => ({
      date: f.date,
      yhat: f.yhat,
      yhat_lower: f.yhat_lower,
      yhat_upper: f.yhat_upper,
      band: [f.yhat_lower, f.yhat_upper] as [number, number],
    })),
  ];

  const lastHistDate = data.historical[data.historical.length - 1]?.date;
  const totalHistorical = data.historical.reduce((s, h) => s + h.count, 0);
  const avgDaily =
    data.historical.length > 0 ? (totalHistorical / data.historical.length).toFixed(1) : '—';
  const avgForecast =
    data.forecast.length > 0
      ? (data.forecast.reduce((s, f) => s + f.yhat, 0) / data.forecast.length).toFixed(1)
      : '—';

  return (
    <div className={cn('forecast-chart', className)}>
      {/* Summary */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <Badge variant="lime">{data.historical.length} days historical</Badge>
        <Badge variant="lime">{data.forecast.length} days forecast</Badge>
        <Badge variant="lime">Avg {avgDaily}/day actual</Badge>
        <Badge variant="lime">Avg {avgForecast}/day predicted</Badge>
        {data.meta.data_mode && (
          <Badge variant={data.meta.data_mode === 'real_only' ? 'lime' : 'default'}>
            {data.meta.data_mode === 'real_only' ? 'Real data only' : 'All data (incl. synthetic)'}
          </Badge>
        )}
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={240} className="outline-none!">
        <ComposedChart
          data={chartData}
          margin={{ top: 4, right: 8, left: -30, bottom: -15 }}
          className="outline-none!"
        >
          <CartesianGrid strokeDasharray="3 3" stroke="var(--grey-300)" className="outline-none!" />
          <XAxis
            dataKey="date"
            tickFormatter={fmtDay}
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
            allowDecimals={false}
            className="outline-none!"
          />
          <Tooltip content={<ForecastTooltip />} />

          {/* Confidence band (forecast region) */}
          <Area dataKey="band" fill="#e1f2ae" fillOpacity={0.25} stroke="none" />

          {/* Historical bars */}
          <Bar dataKey="count" fill="#e1f2ae" radius={[2, 2, 0, 0]} maxBarSize={12} />

          {/* Forecast line */}
          <Line
            type="monotone"
            dataKey="yhat"
            stroke="#9db821"
            strokeWidth={2}
            strokeDasharray="6 3"
            dot={false}
            activeDot={{ r: 3, fill: '#c7f333' }}
          />

          {/* Separator line between historical and forecast */}
          {lastHistDate && (
            <ReferenceLine
              x={lastHistDate}
              stroke="var(--muted-foreground, #94a3b8)"
              strokeDasharray="3 3"
              strokeWidth={1}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};

export default ForecastChart;
