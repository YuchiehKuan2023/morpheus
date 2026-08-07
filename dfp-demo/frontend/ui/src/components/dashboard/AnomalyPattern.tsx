import type { IntradayRhythmCell } from '@/types';
import type { FC } from 'react';
import { GlassCard, InfoTooltip, IntradayRhythm } from '@/components';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  intradayRhythm: IntradayRhythmCell[];
}

const AnomalyPattern: FC<Props> = (props) => {
  const { intradayRhythm } = props;
  const { title, description, tooltip } = DESC.operationalPatterns.components.anomalyPattern;

  return (
    <GlassCard
      title={
        <>
          {title} <InfoTooltip content={tooltip} />
        </>
      }
      description={description}
    >
      <div className="py-4 px-2">
        <IntradayRhythm data={intradayRhythm} />
      </div>
    </GlassCard>
  );
};

export default AnomalyPattern;
