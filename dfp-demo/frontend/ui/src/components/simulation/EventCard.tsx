import type { FC } from 'react';
import { useState } from 'react';
import { cn } from '@/utils';
import type { SimStage, SimulationSession, SimulationUser } from '@/types';
import { ProcessList } from '@/components/simulation';
import { Summary, fromSession } from '@/components/simulation';
import { Badge, Spinner } from '@/components';
import { PROCESS_LABELS, STAGE_LABEL } from '@/constants/simulation';
import { ChevronDown, ChevronRight, ShieldAlert, ShieldCheck } from 'lucide-react';

interface Props {
  session: SimulationSession;
  user?: SimulationUser;
  onOpenAnomalyDetail?: (anomalyId: string, stage: SimStage) => void;
}

function initials(userId: string): string {
  const parts = userId.split('@')[0].split('.');
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

function displayName(userId: string): string {
  const parts = userId.split('@')[0].split('.');
  return parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
}

const isTerminal = (stage: string) =>
  stage === 'complete' || stage === 'clean' || stage === 'failed' || stage === 'labeled';

const EventCard: FC<Props> = ({ session, user, onOpenAnomalyDetail }) => {
  const [expanded, setExpanded] = useState(false);

  // Prefer DB user data; fall back to email-derived values
  const displayNameStr = user?.display_name ?? displayName(session.user_id);
  const avatarInitials = user?.avatar_initials ?? initials(session.user_id);
  const color = user?.avatar_color ?? 'var(--brand-black)';
  const avatarUrl = user?.avatar_url;
  const terminal = isTerminal(session.stage);

  const runningEntry = !terminal
    ? session.stages_log.find((e) => e.status === 'running')
    : undefined;
  const runningLabel = runningEntry
    ? (PROCESS_LABELS[runningEntry.process] ?? runningEntry.process)
    : null;

  return (
    <div
      className={cn(
        'sim-event-card',
        terminal && 'sim-event-card--terminal',
        session.stage === 'failed' && 'sim-event-card--failed',
        session.stage === 'complete' && 'sim-event-card--complete'
      )}
    >
      {/* ── Collapsed row ────────────────────────────────────────────────── */}
      <button
        className="sim-event-card__header focus:outline-none focus:ring-0"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        {/* Avatar */}
        <span
          className="sim-event-card__avatar"
          style={avatarUrl ? undefined : { backgroundColor: color }}
          title={session.user_id}
        >
          {avatarUrl ? (
            <img
              className="sim-event-card__avatar-img"
              src={`/avatar/${avatarUrl}`}
              alt={displayNameStr}
              draggable={false}
            />
          ) : (
            avatarInitials
          )}
        </span>

        {/* User + meta */}
        <div className="sim-event-card__meta">
          <span className="sim-event-card__name">{displayNameStr}</span>
          <div className="sim-event-card__pills">
            <span
              className={cn(
                'sim-badge sim-badge--type',
                session.event_type === 'novel' ? 'sim-badge--novel' : 'sim-badge--clean-type'
              )}
            >
              {session.event_type === 'novel' ? `novel ${session.scenario}` : 'clean'}
            </span>
            <span className="sim-event-card__time">
              {new Date(session.sent_at).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
              })}
            </span>
          </div>
        </div>

        <div className="sim-event-card__badges">
          {runningLabel && (
            <div className="sim-event-card__running-step">
              <Badge>
                <Spinner {...{ height: 2, width: 2, marginBottom: 0 }} />
                <span>{runningLabel}</span>
              </Badge>
            </div>
          )}

          {/* Anomaly score (only when detected) */}
          {session.anomaly_score !== null && (
            <div className="sim-event-card__anomaly-pills">
              {session.anomaly_score !== null && (
                <Badge variant="lime" className="flex items-center gap-1">
                  {session.anomaly_score < 2 ? (
                    <ShieldCheck {...{ width: 14, height: 14 }} />
                  ) : (
                    <ShieldAlert {...{ width: 14, height: 14 }} />
                  )}{' '}
                  <span>
                    Score:{' '}
                    <span {...(session.anomaly_score >= 2 ? { className: 'font-black' } : {})}>
                      {session.anomaly_score?.toFixed(2)}
                    </span>
                  </span>
                </Badge>
              )}
            </div>
          )}

          {/* Stage badge */}
          <div className="sim-event-card__stage">
            <div className="sim-event-card__stage-row">
              <Badge
                {...(['complete', 'clean'].includes(session.stage) ? { variant: 'lime' } : {})}
              >
                {STAGE_LABEL[session.stage] ?? session.stage}
              </Badge>
              {!terminal && <span className="sim-event-card__spinner" aria-label="In progress" />}
            </div>
          </div>

          {/* Button to open anomaly detail dialog */}
          {session.stage === 'complete' && session.anomaly_id && (
            <span
              className="sim-event-card__detail-link dfp-badge cursor-pointer"
              onClick={(e) => {
                e.stopPropagation();
                onOpenAnomalyDetail?.(session.anomaly_id!, session.stage);
              }}
            >
              View
            </span>
          )}
        </div>

        {/* Expand chevron */}
        <span className="sim-event-card__chevron">
          {expanded ? <ChevronDown /> : <ChevronRight />}
        </span>
      </button>

      {/* ── Expanded: ProcessList + anomaly summary ───────────────────────── */}
      {expanded && (
        <div className="sim-event-card__body">
          <ProcessList
            stagesLog={session.stages_log}
            isClean={session.stage === 'clean'}
            anomalyId={session.anomaly_id ?? undefined}
          />

          {/* Anomaly summary — shown once a detection exists */}
          {session.anomaly_id && <Summary data={fromSession(session)} />}
        </div>
      )}
    </div>
  );
};

export default EventCard;
