import type { SimulationStatus } from '@/types/simulation';
import type { FC } from 'react';

interface Props {
  status: SimulationStatus;
  connected: boolean;
}

const Lead: FC<Props> = (props) => {
  const {
    status: { running },
    connected,
  } = props;

  return (
    <div className="sim-drawer__lead">
      <span className="sim-drawer__title">Event Sim</span>
      {running ? (
        <div className="sim-drawer__live">
          <span className="sim-pulse" aria-label="Live" />
          <span className="sim-drawer__live-label">Live</span>
        </div>
      ) : (
        <span className="sim-drawer__idle-label">{connected ? 'Ready' : 'Idle'}</span>
      )}
    </div>
  );
};

export default Lead;
