import type { FC } from 'react';
import { Badge, KPICard } from '@/components';
import { formatDateTime } from '@/utils';
import type { UserDetail } from '@/types';

interface Props {
  detail: UserDetail;
}

const Metrics: FC<Props> = (props) => {
  const { detail } = props;
  const { anomaly_count, critical_count, avg_anomaly_score, last_anomaly_at } = detail;

  return (
    <>
      <KPICard
        title="Total anomalies"
        value={<Badge>{anomaly_count}</Badge>}
        size="xs"
        className="no-border no-shadow"
      />
      <KPICard
        title="Critical"
        value={<Badge>{critical_count}</Badge>}
        size="xs"
        className="no-border no-shadow"
      />
      <KPICard
        title="Avg risk score"
        value={<Badge>{avg_anomaly_score.toFixed(2)}</Badge>}
        size="xs"
        className="no-border no-shadow"
      />
      <KPICard
        title="Last anomaly"
        value={<Badge>{formatDateTime(last_anomaly_at)}</Badge>}
        size="xs"
        className="no-border no-shadow"
      />
    </>
  );
};

export default Metrics;
