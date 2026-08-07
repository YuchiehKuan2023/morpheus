import type { SimulationStatus } from '@/types/simulation';
import type { FC } from 'react';

interface Props {
  status: SimulationStatus;
}

const Stats: FC<Props> = (props) => {
  const {
    events_sent,
    anomalies_detected,
    clean_count,
    total_sent,
    total_anomalies,
    total_clean,
    active_trackers,
    running,
  } = props.status;

  const sentCount = running ? events_sent : total_sent;
  const anomalyCount = running ? anomalies_detected : total_anomalies;
  const cleanCount = running ? clean_count : total_clean;

  return (
    <div className="sim-drawer__stats">
      <span className="sim-stat">
        <span className="sim-stat__value">{sentCount}</span>
        <span className="sim-stat__label">sent</span>
      </span>
      <span className="sim-stat">
        <span className="sim-stat__value">{anomalyCount}</span>
        <span className="sim-stat__label">anomalies</span>
      </span>
      <span className="sim-stat">
        <span className="sim-stat__value">{cleanCount}</span>
        <span className="sim-stat__label">clean</span>
      </span>
      <span className="sim-stat">
        <span className="sim-stat__value">{active_trackers}</span>
        <span className="sim-stat__label">active</span>
      </span>
    </div>
  );
};

export default Stats;
