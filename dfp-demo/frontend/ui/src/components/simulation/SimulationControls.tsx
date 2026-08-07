import type { FC } from 'react';
import { cn } from '@/utils';
import type { SimulationStatus, SimulationUser, SimSpeed } from '@/types';
import { SPEEDS } from '@/constants/simulation';
import { UserSelect } from '..';

interface Props {
  users: SimulationUser[];
  status: SimulationStatus;
  selectedUsers: Set<string>;
  onToggleUser: (uid: string) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  speed: SimSpeed;
  onSpeedChange: (s: SimSpeed) => void;
  error: string | null;
}

const SimulationControls: FC<Props> = ({
  users,
  status,
  selectedUsers,
  onToggleUser,
  onSelectAll,
  onClearSelection,
  speed,
  onSpeedChange,
  error,
}) => {
  return (
    <div className="sim-controls">
      {/* Speed selector — always at top, hidden while running */}
      {!status.running && (
        <>
          <div className="sim-controls__section-label">Speed</div>
          <div className="sim-controls__speed">
            {SPEEDS.map((s) => (
              <button
                key={s.id}
                className={cn(
                  'sim-speed-btn kpi-card no-border no-shadow kpi-card--xs',
                  speed === s.id && 'sim-speed-btn--active kpi-card--dark'
                )}
                onClick={() => onSpeedChange(s.id)}
                title={s.description}
              >
                <span className="sim-speed-btn__label kpi-card__value">{s.label}</span>
                <span className="sim-speed-btn__desc kpi-card__value">{s.description}</span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className="sim-panel__divider -ml-5 -mr-5 mt-2" />

      {/* User multiselect dropdown — always shown */}
      <div className="sim-controls__section-label">Users</div>
      <UserSelect
        users={users}
        selected={selectedUsers}
        disabled={status.running}
        onToggle={onToggleUser}
        onSelectAll={onSelectAll}
        onClearSelection={onClearSelection}
      />

      {/* Error */}
      {error && <p className="sim-controls__error">{error}</p>}
    </div>
  );
};

export default SimulationControls;
