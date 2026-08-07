import { type FC, useEffect, useId, useRef, useState } from 'react';
import type { UserTrendPoint } from '@/types';
import { cn } from '@/utils';
import { TrendingDown, TrendingUp } from 'lucide-react';

interface Props {
  data: UserTrendPoint[];
  days?: number;
  height?: number;
  className?: string;
}

const PAD = { top: 12, right: 0, bottom: 22, left: 12 };

const UserSparkline: FC<Props> = ({ data, days = 0, height = 80, className }) => {
  const [width, setWidth] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const uid = useId();

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Derive the date range from actual data (all-time) or use the days prop as a window
  const today = new Date();
  const earliest =
    data.length > 0
      ? new Date(data[0].bucket)
      : new Date(today.getTime() - (days > 0 ? days : 30) * 86400_000);
  const msPerDay = 86400_000;
  const spanDays = Math.max(Math.round((today.getTime() - earliest.getTime()) / msPerDay) + 1, 2);

  // Build a dense series: one entry per day across the full span
  const byBucket = new Map(data.map((p) => [p.bucket, p]));
  const filled = Array.from({ length: spanDays }, (_, i) => {
    const d = new Date(earliest.getTime() + i * msPerDay);
    const key = d.toISOString().slice(0, 10);
    const found = byBucket.get(key);
    return found ?? { bucket: key, count: 0, avg_score: 0 };
  });

  const maxCount = Math.max(...filled.map((d) => d.count), 1);
  const IW = Math.max(width - PAD.left - PAD.right, 0);
  const IH = height - PAD.top - PAD.bottom;
  const baseline = PAD.top + IH;

  const xscale = (i: number) => PAD.left + (spanDays > 1 ? (i / (spanDays - 1)) * IW : IW / 2);
  const yscale = (v: number) => PAD.top + IH - (v / maxCount) * IH;

  const pts = filled.map((d, i) => ({ x: xscale(i), y: yscale(d.count), ...d }));
  const polyline = pts.map((p) => `${p.x},${p.y}`).join(' ');
  const areaPath =
    `M ${pts[0].x},${baseline} ` +
    pts.map((p) => `L ${p.x},${p.y}`).join(' ') +
    ` L ${pts[pts.length - 1].x},${baseline} Z`;

  // Trend: compare last 7 days avg to the preceding 7 days
  const recentWindow = filled.slice(-7);
  const prevWindow = filled.slice(-14, -7);
  const recentAvg =
    recentWindow.length > 0
      ? recentWindow.reduce((s, d) => s + d.count, 0) / recentWindow.length
      : 0;
  const prevAvg =
    prevWindow.length > 0 ? prevWindow.reduce((s, d) => s + d.count, 0) / prevWindow.length : 0;
  const up = recentAvg > prevAvg;
  const color = up ? 'var(--error-600)' : 'var(--brand-dark-lime)';
  const trendLabel = up ? (
    <TrendingUp width={16} height={16} />
  ) : (
    <TrendingDown width={16} height={16} />
  );
  const trendTitle = data.length === 0 ? 'No data' : `${spanDays}-day trend`;

  const gradId = `spark-${uid.replace(/:/g, '')}`;
  const lastPt = pts[pts.length - 1];
  const firstDate = filled[0].bucket.slice(5).replace('-', '/');
  const lastDate = filled[filled.length - 1].bucket.slice(5).replace('-', '/');

  return (
    <div ref={containerRef} className={cn('user-sparkline', className)}>
      <div className="user-sparkline__header">
        <span className="user-sparkline__title">{trendTitle}</span>
        {data.length > 0 && (
          <span className="user-sparkline__trend" style={{ color }}>
            {trendLabel}
          </span>
        )}
      </div>

      {width > 0 && (
        <svg width={width} height={height} className="user-sparkline__svg" aria-hidden="true">
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>

          {/* Baseline */}
          <line
            x1={PAD.left}
            y1={baseline}
            x2={PAD.left + IW}
            y2={baseline}
            className="user-sparkline__baseline"
          />

          {/* Area fill */}
          <path d={areaPath} fill={`url(#${gradId})`} />

          {/* Line */}
          <polyline
            points={polyline}
            fill="none"
            stroke={color}
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {/* End dot (only when last day has data) */}
          {lastPt.count > 0 && <circle cx={lastPt.x} cy={lastPt.y} r={3} fill={color} />}

          {/* Y-axis: 0 and max labels */}
          <text
            x={PAD.left - 4}
            y={PAD.top}
            dominantBaseline="middle"
            textAnchor="end"
            className="user-sparkline__axis-label"
          >
            {maxCount}
          </text>
          <text
            x={PAD.left - 4}
            y={baseline}
            dominantBaseline="middle"
            textAnchor="end"
            className="user-sparkline__axis-label"
          >
            0
          </text>

          {/* X-axis: date range */}
          <text
            x={PAD.left}
            y={height - 4}
            textAnchor="start"
            className="user-sparkline__axis-label"
          >
            {firstDate}
          </text>
          <text
            x={PAD.left + IW}
            y={height - 4}
            textAnchor="end"
            className="user-sparkline__axis-label"
          >
            {lastDate}
          </text>
        </svg>
      )}
    </div>
  );
};

export default UserSparkline;
