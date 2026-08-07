import { type FC } from 'react';
import { Clock, CircleCheck, CircleX } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui';
import type { HeatmapDay } from '@/types';
import { cn, formatDisplayDate, intensityLevel, toDateStr } from '@/utils';
import { DAY_LABELS, MONTHS } from '@/constants';

interface Props {
  data: HeatmapDay[];
  /** Number of weeks to display, newest on the right. Default: 17 (~4 months). */
  weeks?: number;
  className?: string;
}

type GridCell = {
  date: string;
  count: number;
  max_score: number | null;
  confirmed_count: number;
  false_positive_count: number;
  new_count: number;
} | null;

const ActivityHeatmap: FC<Props> = ({ data, weeks = 17, className }) => {
  const dayMap = new Map<string, HeatmapDay>(data.map((d) => [d.date, d]));
  const max = Math.max(...data.map((d) => d.count), 1);

  // Align grid to start on the Monday of (weeks-1) full weeks ago
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const dowSun = today.getDay(); // 0=Sun
  const daysSinceMonday = dowSun === 0 ? 6 : dowSun - 1;
  const thisMonday = new Date(today);
  thisMonday.setDate(today.getDate() - daysSinceMonday);
  const gridStart = new Date(thisMonday);
  gridStart.setDate(thisMonday.getDate() - (weeks - 1) * 7);

  // Build week columns: each is 7 cells (Mon→Sun), null = future
  const weekColumns: GridCell[][] = [];
  for (let w = 0; w < weeks; w++) {
    const week: GridCell[] = [];
    for (let d = 0; d < 7; d++) {
      const date = new Date(gridStart);
      date.setDate(gridStart.getDate() + w * 7 + d);
      if (date > today) {
        week.push(null); // future
      } else {
        const ds = toDateStr(date);
        const entry = dayMap.get(ds);
        week.push({
          date: ds,
          count: entry?.count ?? 0,
          max_score: entry?.max_score ?? null,
          confirmed_count: entry?.confirmed_count ?? 0,
          false_positive_count: entry?.false_positive_count ?? 0,
          new_count: entry?.new_count ?? 0,
        });
      }
    }
    weekColumns.push(week);
  }

  // Month label per week column: show when month changes
  const monthLabels: (string | null)[] = weekColumns.map((week, i) => {
    const first = week.find((c) => c !== null);
    if (!first) return null;
    const month = new Date(first.date + 'T00:00:00').getMonth();
    if (i === 0) return MONTHS[month];
    const prevFirst = weekColumns[i - 1].find((c) => c !== null);
    if (!prevFirst) return null;
    const prevMonth = new Date(prevFirst.date + 'T00:00:00').getMonth();
    return prevMonth !== month ? MONTHS[month] : null;
  });

  return (
    <TooltipProvider delayDuration={100}>
      <div className={cn('activity-heatmap', className)}>
        {/* Month labels */}
        <div className="activity-heatmap__months">
          <div className="activity-heatmap__day-spacer" />
          {weekColumns.map((_, i) => (
            <div key={i} className="activity-heatmap__month-label">
              {monthLabels[i] ?? ''}
            </div>
          ))}
        </div>

        {/* Grid body */}
        <div className="activity-heatmap__body">
          {/* Day-of-week labels */}
          <div className="activity-heatmap__days">
            {DAY_LABELS.map((label) => (
              <div key={label} className="activity-heatmap__day-label">
                {label}
              </div>
            ))}
          </div>

          {/* Week columns */}
          <div className="activity-heatmap__grid">
            {weekColumns.map((week, wi) => (
              <div key={wi} className="activity-heatmap__week">
                {week.map((cell, di) => {
                  if (cell === null) {
                    return (
                      <div
                        key={di}
                        className="activity-heatmap__cell activity-heatmap__cell--future"
                      />
                    );
                  }
                  const level = intensityLevel(cell.count, max);
                  const isToday = cell.date === toDateStr(today);
                  const label =
                    cell.count === 0
                      ? isToday
                        ? 'No anomalies today'
                        : `No anomalies on ${formatDisplayDate(cell.date)}`
                      : `${cell.count} anomalies on ${formatDisplayDate(cell.date)}`;
                  return (
                    <Tooltip key={di}>
                      <TooltipTrigger asChild>
                        <div
                          className={cn(
                            'activity-heatmap__cell',
                            `activity-heatmap__cell--level-${level}`
                          )}
                          aria-label={label}
                        />
                      </TooltipTrigger>
                      <TooltipContent side="top">
                        {cell.count === 0 ? (
                          <span>{label}</span>
                        ) : (
                          <div className="activity-heatmap__tooltip-content">
                            <div className="activity-heatmap__tooltip-date">
                              {formatDisplayDate(cell.date)}
                            </div>
                            <div className="activity-heatmap__tooltip-total">
                              {cell.count} {cell.count !== 1 ? 'anomalies' : 'anomaly'}
                              {cell.max_score != null && (
                                <span className="activity-heatmap__tooltip-score">
                                  · peak score {cell.max_score.toFixed(1)}
                                </span>
                              )}
                            </div>
                            {(cell.confirmed_count > 0 ||
                              cell.false_positive_count > 0 ||
                              cell.new_count > 0) && (
                              <div className="activity-heatmap__tooltip-breakdown">
                                {cell.confirmed_count > 0 && (
                                  <span className="activity-heatmap__tooltip-confirmed">
                                    <CircleCheck size={10} />
                                    <span>{cell.confirmed_count} confirmed</span>
                                  </span>
                                )}
                                {cell.false_positive_count > 0 && (
                                  <span className="activity-heatmap__tooltip-fp">
                                    <CircleX size={10} />
                                    <span>{cell.false_positive_count} false positive</span>
                                  </span>
                                )}
                                {cell.new_count > 0 && (
                                  <span className="activity-heatmap__tooltip-pending">
                                    <Clock size={10} />
                                    <span>{cell.new_count} new</span>
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
};

export default ActivityHeatmap;
