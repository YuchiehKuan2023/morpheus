import type { RootCauseData } from '@/types';
import type { FC } from 'react';
import { BarChart, GlassCard, InfoTooltip } from '@/components';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  topRootCausesData: RootCauseData[];
}

const TopRootCauses: FC<Props> = (props) => {
  const { topRootCausesData } = props;
  const { title, description, tooltip } = DESC.riskAndUserAnalysis.components.topRootCauses;

  return (
    <GlassCard
      title={
        <>
          {title} <InfoTooltip content={tooltip} />
        </>
      }
      description={description}
    >
      <div className="h-72 pt-6">
        <BarChart data={topRootCausesData} variant="uniform" />
      </div>
    </GlassCard>
  );
};

export default TopRootCauses;
