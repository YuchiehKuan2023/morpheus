import type { SimulationStatus } from '@/types/simulation';
import { cn } from '@/utils';
import type { FC } from 'react';

interface Props {
  status: SimulationStatus;
  selectedUsers: Set<string>;
  canStart: boolean;
  loading: boolean;
  handleToggleRun: () => void;
  onClose: () => void;
}

const Actions: FC<Props> = (props) => {
  const {
    status: { running },
    selectedUsers,
    canStart,
    loading,
    handleToggleRun,
    onClose,
  } = props;

  return (
    <div className="sim-drawer__header-actions">
      <button
        className={cn('sim-run-btn', running && 'sim-run-btn--stop')}
        onClick={handleToggleRun}
        disabled={loading || (!running && !canStart)}
        aria-label={running ? 'Stop simulation' : 'Start simulation'}
        title={running ? 'Stop' : selectedUsers.size ? 'Start' : 'Select users to start'}
      >
        {loading ? <span className="sim-run-btn__spinner" /> : running ? '⏹' : '▶'}
      </button>
      <button className="sim-drawer__close" onClick={onClose} aria-label="Close simulator">
        ✕
      </button>
    </div>
  );
};

export default Actions;
