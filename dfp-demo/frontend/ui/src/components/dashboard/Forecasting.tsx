import type { FC } from 'react';
import { ForecastChart, GlassCard, InfoTooltip } from '@/components';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

const Forecasting: FC = () => {
  const { title, description, tooltip } = DESC.trendForecasting.components.anomalyForecast;

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
        <ForecastChart />
      </div>
    </GlassCard>
  );
};

export default Forecasting;
