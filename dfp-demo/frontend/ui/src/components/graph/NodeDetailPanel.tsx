import type { GraphNode, NodeDetail } from '@/types';
import { NODE_BORDER_COLORS, NODE_COLORS } from './graphConfig';
import { X } from 'lucide-react';

interface Props {
  node: GraphNode;
  detail: NodeDetail | null;
  onClose: () => void;
  onFocusUser?: (userId: string) => void;
}

// Fields suppressed per node label (internal IDs / noise)
const HIDDEN_FIELDS: Record<string, string[]> = {
  User: ['user_id'], // shown as node name already
  Detection: ['detection_id', 'user_id', 'created_at'], // id = name; user visible as edge
  Application: ['name', 'created_at'],
  Device: ['name', 'created_at'],
  Browser: ['name', 'created_at'],
  OperatingSystem: ['name', 'created_at'],
  IPAddress: ['address', 'created_at'],
  ClientApp: ['name', 'created_at'],
  Location: ['city', 'created_at'],
};

function formatKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  const s = String(value);
  // ISO date-time strings (2025-01-15T10:30:00 or neo4j datetime repr)
  if (/^\d{4}-\d{2}-\d{2}[T ]/.test(s)) {
    const d = new Date(s);
    if (!isNaN(d.getTime())) {
      return d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
    }
  }
  return s;
}

function deriveUserInfo(userId: string) {
  const local = userId.split('@')[0] ?? userId;
  const domain = userId.includes('@') ? userId.split('@')[1] : '';
  const parts = local.split(/[._-]/).filter(Boolean);
  const displayName = parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
  const initials = parts
    .slice(0, 2)
    .map((p) => p.charAt(0).toUpperCase())
    .join('');
  return { displayName, domain, initials };
}

export default function NodeDetailPanel({ node, detail, onClose, onFocusUser }: Props) {
  const fillColor = NODE_COLORS[node.label] ?? NODE_COLORS.Unknown;
  const borderColor = NODE_BORDER_COLORS[node.label] ?? NODE_BORDER_COLORS.Unknown;
  const rawProps = detail?.properties ?? {};
  const hidden = HIDDEN_FIELDS[node.label] ?? [];
  const visibleProps = Object.entries(rawProps).filter(([k]) => !hidden.includes(k));

  const isUser = node.label === 'User';
  const userId = String(node.user_id ?? node.name ?? '');
  const userInfo = isUser ? deriveUserInfo(userId) : null;

  return (
    <div className="flex flex-col gap-3 text-sm">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {isUser && userInfo ? (
            // Avatar circle with initials for User nodes
            <span
              className="inline-flex items-center justify-center w-8 h-8 rounded-full shrink-0 text-xs font-bold"
              style={{
                backgroundColor: fillColor,
                border: `2px solid ${borderColor}`,
                color: borderColor,
              }}
            >
              {userInfo.initials}
            </span>
          ) : (
            <span
              className="inline-block w-3 h-3 rounded-full shrink-0 mt-0.5"
              style={{ backgroundColor: fillColor, border: `1.5px solid ${borderColor}` }}
            />
          )}
          <div className="min-w-0">
            <p className="font-semibold text-gray-900 truncate">
              {isUser && userInfo ? userInfo.displayName : String(node.name)}
            </p>
            {isUser && userInfo ? (
              <p className="text-xs text-gray-400 truncate">{userId}</p>
            ) : (
              <p className="text-xs text-gray-500">{node.label}</p>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-700 shrink-0 transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      {/* User extra info row */}
      {isUser && userInfo?.domain && (
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          <span className="px-1.5 py-0.5 bg-gray-100 rounded text-gray-600">{userInfo.domain}</span>
        </div>
      )}

      {/* Properties */}
      {detail === null ? (
        <p className="text-xs text-gray-400 italic">Loading…</p>
      ) : visibleProps.length === 0 ? (
        <p className="text-xs text-gray-400 italic">No additional properties.</p>
      ) : (
        <div className="flex flex-col gap-1.5 max-h-64 overflow-y-auto pr-1">
          {visibleProps.map(([key, value]) => (
            <div key={key} className="flex flex-col gap-0.5 text-xs">
              <span className="text-gray-400 font-medium uppercase tracking-wide text-[10px]">
                {formatKey(key)}
              </span>
              <span className="text-gray-700">{formatValue(value)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Actions */}
      {isUser && onFocusUser && (
        <button
          onClick={() => onFocusUser(userId)}
          className="w-full text-xs py-1.5 rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 transition-colors border border-indigo-200"
        >
          Focus on this user's subgraph →
        </button>
      )}
    </div>
  );
}
