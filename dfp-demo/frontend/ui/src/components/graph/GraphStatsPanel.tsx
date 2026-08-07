import type { GraphStats } from '@/types';
import { NODE_COLORS } from './graphConfig';

interface Props {
  stats: GraphStats | null;
  loading: boolean;
}

const DISPLAY_LABELS = [
  'User',
  'Detection',
  'Application',
  'Device',
  'Browser',
  'OperatingSystem',
  'IPAddress',
  'ClientApp',
  'Location',
] as const;

export default function GraphStatsPanel({ stats, loading }: Props) {
  if (loading) {
    return (
      <div className="space-y-2">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-5 rounded bg-white/5 animate-pulse" />
        ))}
      </div>
    );
  }

  if (!stats) return null;

  const total = stats.total_nodes;

  return (
    <div className="flex flex-col gap-3 text-xs">
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wider">Graph Stats</p>

      <div className="flex gap-4">
        <div>
          <p className="text-lg font-bold text-gray-100">{total.toLocaleString()}</p>
          <p className="text-gray-500">Nodes</p>
        </div>
        <div>
          <p className="text-lg font-bold text-gray-100">
            {stats.total_relationships.toLocaleString()}
          </p>
          <p className="text-gray-500">Edges</p>
        </div>
      </div>

      <div className="flex flex-col gap-1 mt-1">
        {DISPLAY_LABELS.map((label) => {
          const count = stats.node_counts[label] ?? 0;
          if (count === 0) return null;
          const pct = total > 0 ? (count / total) * 100 : 0;
          return (
            <div key={label} className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: NODE_COLORS[label] }}
              />
              <span className="w-24 truncate text-gray-400">{label}</span>
              <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: NODE_COLORS[label],
                    opacity: 0.7,
                  }}
                />
              </div>
              <span className="text-gray-400 w-8 text-right">{count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
