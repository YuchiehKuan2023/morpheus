import type { InvestigationTrendDay } from '@/types/dashboard';
import type { FC } from 'react';
import { GlassCard, InfoTooltip, InvestigationThroughput } from '@/components';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  investigationTrend: InvestigationTrendDay[];
}

const Investigation: FC<Props> = (props) => {
  const { investigationTrend } = props;
  const { title, description, tooltip } =
    DESC.operationalPatterns.components.investigationThroughput;

  return (
    <GlassCard
      title={
        <>
          {title} <InfoTooltip content={tooltip} />
        </>
      }
      description={description}
    >
      <div className="pt-4 pb-2">
        <InvestigationThroughput data={investigationTrend} />
      </div>
    </GlassCard>
  );
};

export default Investigation;
