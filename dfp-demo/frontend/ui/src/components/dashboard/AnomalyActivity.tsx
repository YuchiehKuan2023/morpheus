import type { FC } from 'react';
import { ActivityHeatmap, GlassCard, InfoTooltip } from '@/components';
import type { HeatmapDay } from '@/types/dashboard';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  activityHeatmap: HeatmapDay[];
}

const AnomalyActivity: FC<Props> = (props) => {
  const { activityHeatmap } = props;
  const { title, description, tooltip } = DESC.anomalyIntelligence.components.anomalyActivity;

  return (
    <div className="col-span-2">
      <GlassCard
        title={
          <>
            {title} <InfoTooltip content={tooltip} />
          </>
        }
        description={description}
      >
        <div className="pt-4 pb-2">
          <ActivityHeatmap data={activityHeatmap} />
        </div>
      </GlassCard>
    </div>
  );
};

export default AnomalyActivity;
