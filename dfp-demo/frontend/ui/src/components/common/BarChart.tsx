import { cn } from '@/utils';
import { type FC, useState } from 'react';
import { ChartTooltip } from '@/components';

export interface BarChartEntry {
  label: string;
  value: number;
  color?: string;
  /** The initially selected bar. */
  active?: boolean;
  /** Extra key-value pairs shown in the hover tooltip. */
  meta?: Record<string, string | number | null>;
}

interface Props {
  data: BarChartEntry[];
  /** Show value label above/beside each bar. Default: true */
  showValues?: boolean;
  /** Show axis labels below/beside each bar. Default: true */
  showLabels?: boolean;
  /** Called when the user selects a bar. */
  onSelect?: (entry: BarChartEntry) => void;
  /** 'vertical' (default) renders existing vertical bars; 'horizontal' renders horizontal bars. */
  orientation?: 'vertical' | 'horizontal';
  variant?: 'default' | 'uniform';
  className?: string;
}

/**
 * Pure CSS vertical bar chart. Bars scale to fill the container's full
 * height and each column shares equal width. No external chart library.
 */
const BarChart: FC<Props> = ({
  data,
  showValues = true,
  showLabels = true,
  onSelect,
  orientation = 'vertical',
  variant = 'default',
  className,
}) => {
  const initialActive = data.find((d) => d.active)?.label ?? null;

  const [selected, setSelected] = useState<string | null>(initialActive);
  const [hovered, setHovered] = useState<string | null>(null);

  const max = Math.max(...data.map((d) => d.value), 1);

  const handleSelect = (entry: BarChartEntry) => {
    setSelected(entry.label);
    onSelect?.(entry);
  };

  if (orientation === 'horizontal') {
    return (
      <div className={cn('bar-chart bar-chart--horizontal', className)}>
        {data.map((entry) => {
          const { label, value, color, meta } = entry;

          const isActive = label === selected;
          const isHovered = label === hovered;
          const pct = (value / max) * 100;
          const tooltipEntries = meta ? Object.entries(meta) : [];

          return (
            <div
              key={label}
              className={`bar-chart__row${isActive ? ' bar-chart__row--active' : ''}`}
              onClick={() => handleSelect(entry)}
              onMouseEnter={() => setHovered(label)}
              onMouseLeave={() => setHovered(null)}
              role="button"
              tabIndex={0}
              aria-pressed={isActive}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleSelect(entry);
                }
              }}
            >
              <div className="bar-chart__track">
                <div
                  className="bar-chart__bar"
                  style={{
                    width: `${pct}%`,
                    ...(color && !isActive ? { background: color } : {}),
                  }}
                />
                {showLabels && <div className="bar-chart__label">{label}</div>}
              </div>
              {showValues && <div className="bar-chart__value">{value.toLocaleString()}</div>}
              {isHovered && tooltipEntries.length > 0 && (
                <ChartTooltip
                  title={label}
                  rows={tooltipEntries.map(([key, val]) => ({
                    label: key,
                    value:
                      val === null ? '—' : typeof val === 'number' ? val.toLocaleString() : val,
                  }))}
                  className="bar-chart__tooltip"
                  variant="dark"
                />
              )}
            </div>
          );
        })}
      </div>
    );
  }

  // ── vertical (default) ───────────────────────────────────────────────────
  return (
    <div className={cn('bar-chart', `bar-chart--${variant}`, className)}>
      {data.map((entry) => {
        const { label, value, color, meta } = entry;

        const isActive = label === selected;
        const isHovered = label === hovered;
        const pct = (value / max) * 100;
        const tooltipRows = meta
          ? Object.entries(meta).map(([key, val]) => ({
              label: key,
              value:
                val === null ? '—' : typeof val === 'number' ? val.toLocaleString() : String(val),
            }))
          : [];

        return (
          <div
            key={label}
            className={`bar-chart__col${isActive ? ' bar-chart__col--active' : ''}`}
            onClick={() => handleSelect(entry)}
            onMouseEnter={() => setHovered(label)}
            onMouseLeave={() => setHovered(null)}
            role="button"
            tabIndex={0}
            aria-pressed={isActive}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                handleSelect(entry);
              }
            }}
          >
            <div className="bar-chart__track">
              <div
                className="bar-chart__bar"
                style={{
                  height: `${pct}%`,
                  ...(color && !isActive ? { background: color } : {}),
                }}
              >
                {showValues && <div className="bar-chart__value">{value.toLocaleString()}</div>}
                {isHovered && tooltipRows.length > 0 && (
                  <ChartTooltip
                    title={label}
                    rows={tooltipRows}
                    className="bar-chart__tooltip"
                    variant="dark"
                  />
                )}
              </div>
            </div>
            {showLabels && <div className="bar-chart__label">{label}</div>}
          </div>
        );
      })}
    </div>
  );
};

export default BarChart;
