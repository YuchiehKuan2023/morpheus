import type { FC } from 'react';
import { useState } from 'react';
import { cn, toTitleCase } from '@/utils';
import type { SimProcessEntry, ProcessGroup } from '@/types';
import { GROUP_LABELS, GROUP_ORDER, PROCESS_LABELS } from '@/constants/simulation';
import { Bot, Circle, CircleCheck, CircleX, HatGlasses, RotateCcw, ScanSearch } from 'lucide-react';
import { Spinner, Badge } from '@/components';

interface Props {
  stagesLog: SimProcessEntry[];
  isClean: boolean;
  anomalyId?: string;
}

function groupStatus(entries: SimProcessEntry[]): 'pending' | 'running' | 'completed' | 'error' {
  if (entries.every((e) => e.status === 'pending')) return 'pending';
  if (entries.some((e) => e.status === 'error')) return 'error';
  if (entries.every((e) => e.status === 'completed')) return 'completed';
  if (entries.some((e) => e.status === 'running')) return 'running';
  return 'pending';
}

const StatusIcon: FC<{ status: SimProcessEntry['status'] }> = ({ status }) => {
  if (status === 'completed')
    return <CircleCheck {...{ height: 14, width: 14, color: 'var(--brand-dark-lime)' }} />;
  if (status === 'running') return <Spinner {...{ height: 3, width: 3, marginBottom: 0 }} />;
  if (status === 'error') return <CircleX {...{ height: 14, width: 14 }} />;
  return <Circle {...{ height: 14, width: 14 }} />;
};

const GroupStatusBadge: FC<{ status: ReturnType<typeof groupStatus> }> = ({ status }) => {
  return (
    <Badge {...(status === 'completed' ? { variant: 'lime' } : {})}>{toTitleCase(status)}</Badge>
  );
};

const ProcessIcon: FC<{ process: ProcessGroup }> = ({ process }) => {
  const props = { height: 16, width: 16 };
  return process === 'agent_orchestrator' ? (
    <HatGlasses {...props} />
  ) : process === 'ai_orchestrator' ? (
    <Bot {...props} />
  ) : (
    <ScanSearch {...props} />
  );
};

const ProcessList: FC<Props> = ({ stagesLog, isClean, anomalyId }) => {
  const [retrying, setRetrying] = useState(false);

  const handleRetrigger = async () => {
    if (!anomalyId || retrying) return;
    setRetrying(true);
    try {
      await fetch(`/api/v1/anomalies/${anomalyId}/retrigger`, { method: 'POST' });
    } finally {
      setRetrying(false);
    }
  };

  const byGroup = GROUP_ORDER.reduce<Record<ProcessGroup, SimProcessEntry[]>>(
    (acc, g) => {
      acc[g] = stagesLog.filter((e) => e.group === g);
      return acc;
    },
    { inference: [], ai_orchestrator: [], agent_orchestrator: [] }
  );

  return (
    <div className="sim-process-list">
      {GROUP_ORDER.map((group) => {
        const entries = byGroup[group];

        if (!entries.length) return null;

        const gStatus = groupStatus(entries);
        const isPending = gStatus === 'pending';

        // Skip agent/ai groups entirely for clean events
        if (isClean && group !== 'inference') return null;

        return (
          <div
            key={group}
            className={cn('sim-process-group', isPending && 'sim-process-group--muted')}
          >
            <div className="sim-process-group__header">
              <span className="sim-process-group__label">
                <ProcessIcon process={group} />
                {GROUP_LABELS[group]}
              </span>
              <div className="flex items-center gap-2">
                <GroupStatusBadge status={gStatus} />
                {group === 'agent_orchestrator' && gStatus === 'error' && anomalyId && (
                  <button
                    onClick={handleRetrigger}
                    disabled={retrying}
                    className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                    title="Re-run agent investigation"
                  >
                    {retrying ? (
                      <Spinner height={3} width={3} marginBottom={0} />
                    ) : (
                      <RotateCcw height={11} width={11} />
                    )}
                    {retrying ? 'Retrying…' : 'Retry'}
                  </button>
                )}
              </div>
            </div>
            <div className="sim-process-group__entries">
              {entries.map((entry) => (
                <div
                  key={entry.process}
                  className={cn(
                    'sim-process-entry',
                    entry.status === 'pending' && 'sim-process-entry--muted'
                  )}
                >
                  <StatusIcon status={entry.status} />
                  <div className="sim-process-entry__body">
                    <span className="sim-process-entry__label text-sm">
                      {PROCESS_LABELS[entry.process] ?? entry.process}
                    </span>
                    {entry.detail && (
                      <span className="sim-process-entry__detail block">
                        {entry.ts && (
                          <span className="sim-process-entry__ts">
                            {new Date(entry.ts).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                              second: '2-digit',
                            })}
                          </span>
                        )}{' '}
                        {entry.detail}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default ProcessList;
