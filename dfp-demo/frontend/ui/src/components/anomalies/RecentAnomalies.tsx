import type { FC } from 'react';
import { GlassCard } from '@/components';
import type { DashboardRecentAnomaly } from '@/types';
import { formatRelative } from '@/utils';

interface Props {
  recentAnomalies: DashboardRecentAnomaly[];
}

const RecentAnomalies: FC<Props> = ({ recentAnomalies }) => {
  return (
    <div className="flex gap-4" style={{ alignItems: 'stretch' }}>
      {/* Left 60% — recent anomalies mini-table */}
      <div style={{ flex: '0 0 60%' }}>
        <GlassCard title="Recent Anomalies" description="Latest 10 detections">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-white/10">
                  <th className="pb-2 pr-4 font-medium text-gray-400">User</th>
                  <th className="pb-2 pr-4 font-medium text-gray-400">Time</th>
                  <th className="pb-2 pr-4 font-medium text-gray-400">Root Cause</th>
                  <th className="pb-2 pr-4 font-medium text-gray-400">Score</th>
                  <th className="pb-2 font-medium text-gray-400">Severity</th>
                </tr>
              </thead>
              <tbody>
                {recentAnomalies.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-gray-500">
                      No anomalies detected yet
                    </td>
                  </tr>
                ) : (
                  recentAnomalies.map((a) => (
                    <tr
                      key={a.anomaly_id}
                      className="border-b border-white/5 hover:bg-white/5 transition-colors"
                    >
                      <td
                        className="py-2 pr-4 font-mono text-xs truncate max-w-35"
                        title={a.user_id}
                      >
                        {a.display_name ?? a.user_id.split('@')[0]}
                      </td>
                      <td className="py-2 pr-4 text-gray-400 whitespace-nowrap">
                        {formatRelative(a.timestamp)}
                      </td>
                      <td className="py-2 pr-4">
                        <span
                          className={`incident-badge ${a.severity === 'critical' ? 'lime' : 'light'}`}
                        >
                          {(a.original_event?.appDisplayName as string) ??
                            a.root_cause ??
                            'Unknown'}
                        </span>
                      </td>
                      <td className="py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-1.5 rounded-full bg-white/10 overflow-hidden">
                            <div
                              className="h-full rounded-full"
                              style={{
                                width: `${Math.min((a.anomaly_score / 10) * 100, 100)}%`,
                                background: 'var(--brand-dark-lime)',
                              }}
                            />
                          </div>
                          <span className="text-xs tabular-nums">{a.anomaly_score.toFixed(2)}</span>
                        </div>
                      </td>
                      <td className="py-2">
                        <span
                          className={`incident-badge ${a.severity === 'critical' ? 'lime' : a.severity === 'high' ? '' : 'light'}`}
                        >
                          {a.severity}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </GlassCard>
      </div>
    </div>
  );
};

export default RecentAnomalies;
