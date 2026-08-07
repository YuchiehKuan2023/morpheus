import type { FC, ReactNode } from 'react';

interface TooltipRow {
  label: ReactNode;
  value: ReactNode;
}

interface ChartTooltipProps {
  title: ReactNode;
  rows: TooltipRow[];
  minWidth?: string;
  className?: string;
  variant?: 'default' | 'dark';
}

/**
 * Reusable chart tooltip component with consistent styling
 * Used across all dashboard charts for uniform tooltip appearance
 */
const ChartTooltip: FC<ChartTooltipProps> = ({
  title,
  rows,
  minWidth = '220px',
  className,
  variant,
}) => {
  const classNames = className ? `chart-tooltip ${className}` : 'chart-tooltip';
  const backgroundColor = variant === 'dark' ? 'var(--brand-black)' : 'var(--brand-pale-lime)';
  const color = variant === 'dark' ? 'var(--white)' : 'var(--grey-900)';

  return (
    <div
      className={classNames}
      style={{
        fontSize: '12px',
        backgroundColor,
        border: 'none',
        borderRadius: '12px',
        padding: '8px 12px',
        minWidth,
      }}
    >
      <div
        style={{
          fontWeight: 600,
          marginBottom: '0',
          color,
          borderBottom: 'none',
          paddingBottom: '2px',
        }}
      >
        {title}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
        {rows.map((row, index) => (
          <div
            key={index}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '6px',
            }}
          >
            <span style={{ color, fontSize: '11px', fontWeight: 500 }}>{row.label}:</span>
            <span style={{ color, fontWeight: 600, fontSize: '11px' }}>{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ChartTooltip;
