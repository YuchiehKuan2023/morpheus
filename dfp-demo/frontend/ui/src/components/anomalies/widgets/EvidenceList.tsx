import { Badge } from '@/components';
import { TYPE_LABEL } from '@/constants/simulation';
import type { EvidenceItem } from '@/types/simulation';
import { cn, toTitleCase } from '@/utils';
import type { FC } from 'react';

interface Props {
  items: EvidenceItem[];
}

export const EvidenceList: FC<Props> = (props) => {
  const { items } = props;

  return (
    <div className="space-y-2">
      {items.map((item, i) => {
        const typeLabel = TYPE_LABEL[item.type] ?? item.type;
        const hasMetrics = item.severity || item.metric || item.z_score != null;

        return (
          <div key={i} className="glass-card glass-card--xs no-border no-shadow rounded-2xl!">
            <div className="flex flex-col gap-1.5">
              <div
                className={cn('text-xs font-semibold text-foreground pl-1', hasMetrics && 'mb-1')}
              >
                {typeLabel} ({item.description})
              </div>
              {hasMetrics && (
                <div className="flex flex-wrap gap-2">
                  {item.severity && <Badge variant="lime">{toTitleCase(item.severity)}</Badge>}
                  {item.metric && (
                    <Badge variant="lime">
                      {toTitleCase(item.metric.replace(/_/g, ' ').replace('kmph', ''))}
                      {item.value != null &&
                        `: ${item.value}${item.metric === 'travel_speed_kmph' ? ' km/h' : ''}`}
                    </Badge>
                  )}
                  {item.z_score != null && (
                    <Badge variant="lime">z={item.z_score.toFixed(2)}</Badge>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
