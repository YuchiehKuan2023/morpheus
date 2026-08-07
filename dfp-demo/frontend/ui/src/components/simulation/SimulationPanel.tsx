import type { FC } from 'react';
import type {
  FilterTab,
  SessionCounts,
  SimulationSession,
  SimulationStatus,
  SimulationUser,
  SimSpeed,
} from '@/types';
import { SimulationControls, EventFeed } from '@/components';

interface Props {
  sessions: SimulationSession[];
  counts: SessionCounts;
  page: number;
  totalPages: number;
  activeTab: FilterTab;
  onPageChange: (page: number) => void;
  onTabChange: (tab: FilterTab) => void;
  status: SimulationStatus;
  users: SimulationUser[];
  selectedUsers: Set<string>;
  onToggleUser: (uid: string) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  speed: SimSpeed;
  onSpeedChange: (s: SimSpeed) => void;
  error: string | null;
}

const SimulationPanel: FC<Props> = ({
  sessions,
  counts,
  page,
  totalPages,
  activeTab,
  onPageChange,
  onTabChange,
  status,
  users,
  selectedUsers,
  onToggleUser,
  onSelectAll,
  onClearSelection,
  speed,
  onSpeedChange,
  error,
}) => {
  return (
    <div className="sim-panel">
      <SimulationControls
        users={users}
        status={status}
        selectedUsers={selectedUsers}
        onToggleUser={onToggleUser}
        onSelectAll={onSelectAll}
        onClearSelection={onClearSelection}
        speed={speed}
        onSpeedChange={onSpeedChange}
        error={error}
      />
      <div className="sim-panel__divider" />
      <EventFeed
        sessions={sessions}
        counts={counts}
        page={page}
        totalPages={totalPages}
        users={users}
        activeTab={activeTab}
        onPageChange={onPageChange}
        onTabChange={onTabChange}
      />
    </div>
  );
};

export default SimulationPanel;
