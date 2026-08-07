import type { FC } from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui';
import type { StatsTrendEntry } from '@/types';

interface Props {
  trend: StatsTrendEntry;
}

/**
 * Compact trend indicator rendered inside the KPI card icon slot (42×42px circle).
 * Shows an up/down arrow and the absolute delta percentage.
 * Hovering reveals a tooltip with the exact current vs previous counts.
 */
const TrendBadge: FC<Props> = ({ trend }) => {
  const direction = trend.delta_pct > 0 ? 'up' : trend.delta_pct < 0 ? 'down' : 'neutral';
  const abs = Math.abs(trend.delta_pct);
  // Show one decimal only when < 10 to keep it dense
  const label = abs === 0 ? `${abs}%` : abs < 10 ? `${abs.toFixed(1)}%` : `${Math.round(abs)}%`;
  const Icon = direction === 'up' ? TrendingUp : direction === 'down' ? TrendingDown : Minus;
  const ariaDirection = direction === 'up' ? 'Up' : direction === 'down' ? 'Down' : 'No change';

  const tooltipText =
    direction === 'neutral'
      ? `No change \u2014 ${trend.current} detections in both the current and previous 7-day periods.`
      : `${trend.current} detections this week vs ${trend.previous} last week \u2014 a ${label} ${direction === 'up' ? 'increase' : 'decrease'} compared to the previous 7-day period.`;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className={`trend-badge trend-badge--${direction}`}
          aria-label={`${ariaDirection} ${label} vs previous 7 days`}
        >
          <Icon className="trend-badge__arrow h-4 w-4 font-bold" aria-hidden="true" />
          <span className="trend-badge__label">{label}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-xs leading-relaxed">
        {tooltipText}
      </TooltipContent>
    </Tooltip>
  );
};

export default TrendBadge;
