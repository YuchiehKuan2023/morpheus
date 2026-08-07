import type { FC } from 'react';
import {
  CarouselNavigation,
  GlassCard,
  GridCols,
  InfoTooltip,
  KPICard,
  MetricsGauge,
  SectionTitle,
  UserCard,
} from '@/components';
import type { AnomaliesStatusStats, TopUser, UserMetrics } from '@/types';
import { Carousel, CarouselContent, CarouselItem, type CarouselApi } from '../ui';
import { GAUGES, USER_ANOMALY_STATS as STATS } from '@/constants';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  statusStats: AnomaliesStatusStats;
  topUsers: TopUser[];
  userMetrics: UserMetrics | null;
  carouselApi: CarouselApi;
  setCarouselApi: ((api: CarouselApi | undefined) => void) | undefined;
}

const Users: FC<Props> = (props) => {
  const {
    statusStats: { new: newCount, resolved, pending },
    topUsers: users,
    userMetrics,
    carouselApi,
    setCarouselApi,
  } = props;

  const { title, description, tooltip } = DESC.riskAndUserAnalysis.components.riskScoreAnalysis;

  return (
    <GlassCard
      title={
        <>
          {title} <InfoTooltip content={tooltip} />
        </>
      }
      description={description}
      className="h-full"
    >
      <GridCols cols={3} className="mt-4 mb-4">
        <KPICard value={resolved} {...{ ...STATS.resolved }} />
        <KPICard value={newCount} {...{ ...STATS.new }} />
        <KPICard value={pending} {...{ ...STATS.pending }} />
      </GridCols>

      {/* Fleet-wide metric gauges */}
      {userMetrics && (
        <GridCols cols={5} className="mb-4">
          {GAUGES.map((def) => (
            <MetricsGauge key={def.key} def={def} value={userMetrics[def.key]} />
          ))}
        </GridCols>
      )}

      {/* Carousel */}
      <div className="pt-4 mt-6">
        <div className="flex flex-row items-center justify-between mb-4">
          <SectionTitle
            title="Top users by anomaly volume"
            description="Users with the highest number of detected anomalies in the current period"
          />
          <CarouselNavigation {...{ carouselApi }} />
        </div>
        <Carousel
          opts={{ align: 'start', slidesToScroll: 2 }}
          className="w-full"
          setApi={setCarouselApi}
        >
          <CarouselContent>
            {users.map((user) => (
              <CarouselItem key={user.username} className="basis-1/2">
                <UserCard user={user} />
              </CarouselItem>
            ))}
          </CarouselContent>
        </Carousel>
      </div>
    </GlassCard>
  );
};

export default Users;
