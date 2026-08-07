import type { FC } from 'react';
import { useState, useEffect, useCallback } from 'react';
import { cn } from '@/utils';
import type { FilterTab, SimSpeed } from '@/types';
import { useSimulation } from '@/hooks';
import { Actions, Lead, SimulationPanel, Stats } from '../simulation';

interface Props {
  open: boolean;
  onClose: () => void;
}

const SimulationDrawer: FC<Props> = ({ open, onClose }) => {
  const {
    sessions,
    counts,
    page,
    totalPages,
    status,
    users,
    connected,
    fetchSessions,
    startSimulation,
    stopSimulation,
  } = useSimulation();

  const [activeTab, setActiveTab] = useState<FilterTab>('all');
  const [selectedUsers, setSelectedUsers] = useState<Set<string>>(new Set());
  const [speed, setSpeed] = useState<SimSpeed>('demo');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handlePageChange = useCallback(
    (newPage: number) => {
      fetchSessions(newPage, activeTab);
    },
    [fetchSessions, activeTab]
  );

  const handleTabChange = useCallback(
    (tab: FilterTab) => {
      setActiveTab(tab);
      fetchSessions(1, tab);
    },
    [fetchSessions]
  );

  // Close on Escape key
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Prevent body scroll while open
  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  function toggleUser(uid: string) {
    setSelectedUsers((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });
  }

  function selectAll() {
    setSelectedUsers(new Set(users.map((u) => u.user_id)));
  }

  function clearSelection() {
    setSelectedUsers(new Set());
  }

  async function handleToggleRun() {
    setLoading(true);
    setError(null);
    try {
      if (status.running) {
        await stopSimulation();
      } else {
        if (!selectedUsers.size) return;
        await startSimulation([...selectedUsers], speed);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Operation failed');
    } finally {
      setLoading(false);
    }
  }

  const canStart = !status.running && selectedUsers.size > 0;

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn('sim-drawer__backdrop', open && 'sim-drawer__backdrop--visible')}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer panel */}
      <aside
        className={cn('sim-drawer', open && 'sim-drawer--open')}
        aria-label="Event Simulator"
        role="complementary"
      >
        <div className="sim-drawer__header">
          {/* Title + live indicator */}
          <Lead {...{ status, connected }} />

          {/* Stats */}
          <Stats {...{ status }} />

          {/* Actions: run toggle + close */}
          <Actions {...{ status, selectedUsers, canStart, loading, handleToggleRun, onClose }} />
        </div>

        <div className="sim-drawer__body">
          <SimulationPanel
            sessions={sessions}
            counts={counts}
            page={page}
            totalPages={totalPages}
            activeTab={activeTab}
            onPageChange={handlePageChange}
            onTabChange={handleTabChange}
            status={status}
            users={users}
            selectedUsers={selectedUsers}
            onToggleUser={toggleUser}
            onSelectAll={selectAll}
            onClearSelection={clearSelection}
            speed={speed}
            onSpeedChange={setSpeed}
            error={error}
          />
        </div>
      </aside>
    </>
  );
};

export default SimulationDrawer;
