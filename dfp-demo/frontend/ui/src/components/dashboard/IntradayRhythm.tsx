import { type FC, useEffect, useRef, useState } from 'react';
import type { IntradayRhythmCell } from '@/types';
import { cn } from '@/utils';
import { BUBBLE_PALETTE } from '@/constants';
import { ChartTooltip } from '@/components';

interface Props {
  data: IntradayRhythmCell[];
  className?: string;
}

type View = 'dow' | 'hour';

const DOW_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
// Axis labels (short bucket notation) and full tooltip labels for hour view
const HOUR_LABELS = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}h`);
const HOUR_TOOLTIP_LABELS = Array.from(
  { length: 24 },
  (_, i) => `${String(i).padStart(2, '0')}:00 - ${String(i).padStart(2, '0')}:59`
);

const M = { top: 28, right: 20, bottom: 0, left: 25 };
const VH = 290;
const IH = VH - M.top - M.bottom;
const PLOT_BOTTOM = M.top + IH;
// Categorical palette — one colour per bucket, cycles if needed
const PALETTE = BUBBLE_PALETTE;

interface BubblePoint {
  label: string;
  tooltipLabel: string;
  count: number;
  avg_score: number;
}

interface TooltipState {
  point: BubblePoint;
  x: number;
  y: number;
}

const yTicks = (maxCount: number): number[] => {
  const raw = maxCount / 5;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
  const step = Math.ceil(raw / mag) * mag;

  return Array.from({ length: 6 }, (_, i) => i * step).filter((v) => v <= maxCount * 1.15);
};

const IntradayRhythm: FC<Props> = ({ data, className }) => {
  const [view, setView] = useState<View>('hour');
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [svgWidth, setSvgWidth] = useState(0);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setSvgWidth(Math.floor(entry.contentRect.width));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const IW = Math.max(svgWidth - M.left - M.right, 0);

  // Aggregate by DOW: sum counts, avg scores across all hours for each day
  const byDow: BubblePoint[] = DOW_LABELS.map((label, di) => {
    const cells = data.filter((c) => c.dow === di);
    const count = cells.reduce((s, c) => s + c.count, 0);
    const avg_score = cells.length ? cells.reduce((s, c) => s + c.avg_score, 0) / cells.length : 0;

    return { label, tooltipLabel: label, count, avg_score };
  });

  // Aggregate by hour: sum counts, avg scores across all DOWs for each hour
  const byHour: BubblePoint[] = HOUR_LABELS.map((label, hi) => {
    const cells = data.filter((c) => c.hour === hi);
    const count = cells.reduce((s, c) => s + c.count, 0);
    const avg_score = cells.length ? cells.reduce((s, c) => s + c.avg_score, 0) / cells.length : 0;

    return { label, tooltipLabel: HOUR_TOOLTIP_LABELS[hi], count, avg_score };
  });

  const points = view === 'dow' ? byDow : byHour;
  const maxCount = Math.max(...points.map((p) => p.count), 1);
  const ticks = yTicks(maxCount);

  const n = points.length;
  const colWidth = IW / n;
  // Scale bubble radius to column width so hour-view bubbles don't overlap
  const maxBubbleR = Math.min(32, colWidth * 0.52);
  const PLOT_TOP = M.top + maxBubbleR + 4;

  const ycenter = (count: number, max: number) =>
    PLOT_BOTTOM - (count / max) * (PLOT_BOTTOM - PLOT_TOP);
  const radius = (count: number, max: number) =>
    count === 0 ? 0 : maxBubbleR * (0.65 + 0.85 * Math.sqrt(count / max));
  const bubbleColor = (i: number): string => PALETTE[i % PALETTE.length];
  const xcenter = (i: number) => M.left + (i + 0.5) * colWidth;
  // For hour view show every 3rd label only
  const showXLabel = (i: number) => view === 'dow' || i % 3 === 0;

  return (
    <div
      ref={containerRef}
      className={cn('intraday-rhythm', className)}
      style={{ position: 'relative' }}
    >
      {/* View toggle */}
      <div className="intraday-rhythm__toggle">
        <button
          className={cn(
            'intraday-rhythm__toggle-btn',
            view === 'dow' && 'intraday-rhythm__toggle-btn--active'
          )}
          onClick={() => {
            setTooltip(null);
            setView('dow');
          }}
        >
          By day of week
        </button>
        <button
          className={cn(
            'intraday-rhythm__toggle-btn',
            view === 'hour' && 'intraday-rhythm__toggle-btn--active'
          )}
          onClick={() => {
            setTooltip(null);
            setView('hour');
          }}
        >
          By hour of day
        </button>
      </div>

      {svgWidth > 0 && (
        <svg
          viewBox={`0 0 ${svgWidth} ${VH}`}
          width={svgWidth}
          height={VH}
          aria-label="Anomaly rhythm chart"
          className="intraday-rhythm__svg"
        >
          {/* Y grid lines + labels */}
          {ticks.map((v) => {
            const y = ycenter(v, maxCount);
            return (
              <g key={v}>
                <line
                  x1={M.left}
                  y1={y}
                  x2={M.left + IW}
                  y2={y}
                  className="intraday-rhythm__gridline"
                />
                <text
                  x={M.left - 6}
                  y={y}
                  dominantBaseline="middle"
                  textAnchor="end"
                  className="intraday-rhythm__axis-label"
                >
                  {v}
                </text>
              </g>
            );
          })}

          {/* X axis baseline */}
          <line
            x1={M.left}
            y1={PLOT_BOTTOM}
            x2={M.left + IW}
            y2={PLOT_BOTTOM}
            className="intraday-rhythm__axis-line"
          />

          {/* X axis labels */}
          {points.map((_, i) =>
            showXLabel(i) ? (
              <text
                key={i}
                x={xcenter(i)}
                y={VH - M.bottom + 14}
                textAnchor="middle"
                className="intraday-rhythm__axis-label"
              >
                {points[i].label}
              </text>
            ) : null
          )}

          {/* Bubbles — render hovered last so it paints on top */}
          {[...points.keys()]
            .filter((i) => i !== hoveredIndex)
            .concat(hoveredIndex !== null && points[hoveredIndex] ? [hoveredIndex] : [])
            .map((i) => {
              const p = points[i];
              const r = radius(p.count, maxCount);
              if (r === 0) return null;
              const bcx = xcenter(i);
              const bcy = ycenter(p.count, maxCount);
              const isHovered = i === hoveredIndex;
              return (
                <g
                  key={i}
                  style={{
                    transformOrigin: `${bcx}px ${bcy}px`,
                    transform: isHovered ? 'scale(1.25)' : 'scale(1)',
                    transition: 'transform 0.2s ease',
                  }}
                  onMouseMove={(e) => {
                    const rect = containerRef.current?.getBoundingClientRect();
                    if (!rect) return;
                    setHoveredIndex(i);
                    setTooltip({ point: p, x: e.clientX - rect.left, y: e.clientY - rect.top });
                  }}
                  onMouseLeave={() => {
                    setHoveredIndex(null);
                    setTooltip(null);
                  }}
                >
                  <circle
                    cx={bcx}
                    cy={bcy}
                    r={r}
                    className="intraday-rhythm__bubble"
                    style={{ fill: bubbleColor(i), stroke: '#ffffff', strokeWidth: 2 }}
                  />
                  {r >= 12 && (
                    <text
                      x={bcx}
                      y={bcy}
                      dominantBaseline="central"
                      textAnchor="middle"
                      className="intraday-rhythm__bubble-label"
                    >
                      {p.count}
                    </text>
                  )}
                </g>
              );
            })}
        </svg>
      )}

      {/* HTML tooltip overlay — follows cursor, flips left/right at boundaries */}
      {tooltip &&
        (() => {
          const TT_W = 220;
          const onRight = tooltip.x + 12 + TT_W <= svgWidth;
          return (
            <div
              style={{
                position: 'absolute',
                ...(onRight ? { left: tooltip.x + 12 } : { left: tooltip.x - 12 - TT_W }),
                top: tooltip.y - 8,
                transform: 'translateY(-100%)',
                pointerEvents: 'none',
                zIndex: 10,
              }}
            >
              <ChartTooltip
                title={tooltip.point.tooltipLabel}
                rows={[
                  { label: 'Anomalies', value: String(tooltip.point.count) },
                  { label: 'Avg score', value: tooltip.point.avg_score.toFixed(2) },
                ]}
                variant="dark"
              />
            </div>
          );
        })()}
    </div>
  );
};

export default IntradayRhythm;
