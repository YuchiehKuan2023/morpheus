import type { FC } from 'react';
import { useMemo, useState } from 'react';
import type {
  FilterTab,
  SessionCounts,
  SimStage,
  SimulationSession,
  SimulationUser,
} from '@/types';
import { EventCard, AnomalyDetailDialog } from '@/components';
import { TABS } from '@/constants/simulation';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface Props {
  /** Current page of sessions from the server. */
  sessions: SimulationSession[];
  /** Counts across all sessions (not just current page). */
  counts: SessionCounts;
  /** Current 1-based page number. */
  page: number;
  /** Total pages for the active tab. */
  totalPages: number;
  users: SimulationUser[];
  activeTab: FilterTab;
  /** Request a new page + tab from the server. */
  onPageChange: (page: number) => void;
  onTabChange: (tab: FilterTab) => void;
}

const EventFeed: FC<Props> = ({
  sessions,
  counts,
  page,
  totalPages,
  users,
  activeTab,
  onPageChange,
  onTabChange,
}) => {
  const [detailSession, setDetailSession] = useState<{ anomalyId: string; stage: SimStage } | null>(
    null
  );

  const userMap = useMemo(() => new Map(users.map((u) => [u.user_id, u])), [users]);

  const tabCount = (tab: FilterTab): number => counts[tab] ?? 0;

  return (
    <>
      <div className="sim-feed">
        {/* Tab bar */}
        <div className="sim-feed__tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              className={`sim-feed__tab${activeTab === tab.id ? ' sim-feed__tab--active' : ''}`}
              onClick={() => onTabChange(tab.id)}
            >
              {tab.label}
              <span className="sim-feed__tab-count">{tabCount(tab.id)}</span>
            </button>
          ))}
        </div>

        {/* Event list */}
        <div className="sim-feed__list">
          <div className="flex flex-col gap-1">
            {sessions.length === 0 ? (
              <p className="sim-feed__empty">
                {counts.all === 0
                  ? 'Start the simulator to see events flowing through the pipeline.'
                  : 'No events match this filter.'}
              </p>
            ) : (
              sessions.map((session) => (
                <EventCard
                  key={session.session_id}
                  session={session}
                  user={userMap.get(session.user_id)}
                  onOpenAnomalyDetail={(id, stage) => setDetailSession({ anomalyId: id, stage })}
                />
              ))
            )}
          </div>
        </div>
        {/* Pagination */}
        {totalPages > 1 && (
          <div className="sim-feed__pagination">
            <button
              className="sim-feed__page-btn"
              onClick={() => onPageChange(Math.max(1, page - 1))}
              disabled={page === 1}
            >
              <ChevronLeft width={12} height={12} /> <span>Prev</span>
            </button>
            <span className="sim-feed__page-info">
              {page} / {totalPages}
            </span>
            <button
              className="sim-feed__page-btn"
              onClick={() => onPageChange(Math.min(totalPages, page + 1))}
              disabled={page === totalPages}
            >
              <span>Next</span> <ChevronRight width={12} height={12} />
            </button>
          </div>
        )}
      </div>

      <AnomalyDetailDialog
        anomalyId={detailSession?.anomalyId ?? null}
        stage={detailSession?.stage}
        open={detailSession !== null}
        onClose={() => setDetailSession(null)}
      />
    </>
  );
};

export default EventFeed;
