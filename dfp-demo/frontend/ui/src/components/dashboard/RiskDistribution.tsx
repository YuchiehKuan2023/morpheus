import type { FC } from 'react';
import { BarChart, GlassCard, InfoTooltip } from '@/components';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';
import type { RiskDistributionData } from '@/types/dashboard';

interface Props {
  riskDistributionData: RiskDistributionData[];
}

const RiskDistribution: FC<Props> = (props) => {
  const { riskDistributionData } = props;
  const { title, description, tooltip } = DESC.riskAndUserAnalysis.components.riskDistribution;

  return (
    <GlassCard
      title={
        <>
          {title} <InfoTooltip content={tooltip} />
        </>
      }
      description={description}
    >
      <div className="h-70 pt-6">
        <BarChart data={riskDistributionData} />
      </div>
    </GlassCard>
  );
};

export default RiskDistribution;
