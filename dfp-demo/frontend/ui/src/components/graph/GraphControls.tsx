import { useState } from 'react';
import {
  ZoomIn,
  ZoomOut,
  Maximize2,
  RotateCcw,
  Search,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import type { GraphVizRef } from './GraphVisualization';
import type { GraphFilters, GraphNode, GraphStats, NodeDetail, NodeLabel } from '@/types';
import { NODE_COLORS } from './graphConfig';
import NodeDetailPanel from './NodeDetailPanel';
import { cn } from '@/utils';

const RELATIONSHIP_TYPES = [
  'GENERATED',
  'ACCESSED',
  'FROM_DEVICE',
  'USED_BROWSER',
  'ON_OS',
  'FROM_IP',
  'VIA_CLIENT',
  'FROM_LOCATION',
] as const;

const ALL_LABELS: NodeLabel[] = [
  'User',
  'Detection',
  'Application',
  'Device',
  'Browser',
  'OperatingSystem',
  'IPAddress',
  'ClientApp',
  'Location',
];

interface Props {
  filters: GraphFilters;
  stats: GraphStats | null;
  visibleNodes: number;
  visibleLinks: number;
  expandedCount: number;
  vizRef: React.MutableRefObject<GraphVizRef | null>;
  selectedNode: GraphNode | null;
  nodeDetail: NodeDetail | null;
  onToggleLabel: (label: NodeLabel) => void;
  onToggleRelType: (type: string) => void;
  onSearchChange: (q: string) => void;
  onReset: () => void;
  onDeselectNode: () => void;
  onFocusUser: (userId: string) => void;
}

const BTN =
  'flex items-center gap-2 px-2 py-1.5 rounded-md text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors text-left';

export default function GraphControls({
  filters,
  stats,
  visibleNodes,
  visibleLinks,
  expandedCount,
  vizRef,
  selectedNode,
  nodeDetail,
  onToggleLabel,
  onToggleRelType,
  onSearchChange,
  onReset,
  onDeselectNode,
  onFocusUser,
}: Props) {
  const [nodeTypesOpen, setNodeTypesOpen] = useState(true);
  const [relTypesOpen, setRelTypesOpen] = useState(false);

  return (
    <div className="flex flex-col gap-0 text-xs select-none">
      {/* ── Selected node detail (shown above everything else) ─────────── */}
      {selectedNode && (
        <div className="px-3 py-3 border-b border-gray-100">
          <NodeDetailPanel
            node={selectedNode}
            detail={nodeDetail}
            onClose={onDeselectNode}
            onFocusUser={onFocusUser}
          />
        </div>
      )}

      {/* ── Node / edge count ─────────────────────────────────────────── */}
      <div className="px-3 py-2.5 border-b border-gray-100">
        <p className="text-gray-900 font-medium">
          {visibleNodes.toLocaleString()} nodes · {visibleLinks.toLocaleString()} edges
        </p>
        <p className="text-gray-400 mt-0.5 leading-snug">
          Right-click to expand · Click to select · Drag to pin
          {expandedCount > 0 && ` · ${expandedCount} expanded`}
        </p>
      </div>

      {/* ── View controls ─────────────────────────────────────────────── */}
      <div className="px-3 py-2.5 border-b border-gray-100">
        <p className="text-gray-500 uppercase tracking-wider text-[10px] font-medium mb-2">
          View Controls
        </p>
        <div className="flex flex-col gap-1">
          <button onClick={() => vizRef.current?.zoomIn()} className={BTN}>
            <ZoomIn size={13} className="shrink-0 text-gray-500" />
            Zoom In
          </button>
          <button onClick={() => vizRef.current?.zoomOut()} className={BTN}>
            <ZoomOut size={13} className="shrink-0 text-gray-500" />
            Zoom Out
          </button>
          <button onClick={() => vizRef.current?.fitView()} className={BTN}>
            <Maximize2 size={13} className="shrink-0 text-gray-500" />
            Fit to Screen
          </button>
          <button
            onClick={() => {
              vizRef.current?.resetGraph();
              onReset();
            }}
            className={BTN}
          >
            <RotateCcw size={13} className="shrink-0 text-gray-500" />
            Reset Graph
          </button>
        </div>
      </div>

      {/* ── Search ────────────────────────────────────────────────────── */}
      <div className="px-3 py-2.5 border-b border-gray-100">
        <p className="text-gray-500 uppercase tracking-wider text-[10px] font-medium mb-2">
          Search
        </p>
        <div className="relative">
          <Search
            size={12}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none"
          />
          <input
            type="text"
            placeholder="Search by node name…"
            value={filters.searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full pl-7 pr-2 py-1.5 text-xs rounded-md bg-gray-50 border border-gray-200 text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
      </div>

      {/* ── Node Types ────────────────────────────────────────────────── */}
      <div className="border-b border-gray-100">
        <button
          onClick={() => setNodeTypesOpen((o) => !o)}
          className="w-full flex items-center justify-between px-3 py-2.5 text-gray-600 hover:text-gray-900 transition-colors"
        >
          <span className="uppercase tracking-wider text-[10px] font-medium text-gray-500">
            Node Types
          </span>
          {nodeTypesOpen ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </button>
        {nodeTypesOpen && (
          <div className="px-3 pb-2.5 flex flex-col gap-1">
            {ALL_LABELS.map((label) => {
              const active = filters.visibleLabels.has(label);
              const count = stats?.node_counts[label] ?? 0;
              return (
                <button
                  key={label}
                  onClick={() => onToggleLabel(label)}
                  className={cn(
                    'flex items-center gap-2 px-1 py-0.5 rounded text-left transition-colors',
                    active ? 'text-gray-800' : 'text-gray-400'
                  )}
                >
                  <span
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: NODE_COLORS[label], opacity: active ? 1 : 0.3 }}
                  />
                  <span className="flex-1 truncate">{label}</span>
                  {count > 0 && <span className="text-gray-400 text-[10px]">{count}</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Relationship Types ────────────────────────────────────────── */}
      <div className="border-b border-gray-100">
        <button
          onClick={() => setRelTypesOpen((o) => !o)}
          className="w-full flex items-center justify-between px-3 py-2.5 text-gray-600 hover:text-gray-900 transition-colors"
        >
          <span className="uppercase tracking-wider text-[10px] font-medium text-gray-500">
            Relationships
          </span>
          {relTypesOpen ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </button>
        {relTypesOpen && (
          <div className="px-3 pb-2.5 flex flex-col gap-1">
            {RELATIONSHIP_TYPES.map((type) => {
              const active = !filters.hiddenRelTypes?.has(type);
              const count = stats?.relationship_counts[type] ?? 0;
              return (
                <button
                  key={type}
                  onClick={() => onToggleRelType(type)}
                  className={cn(
                    'flex items-center gap-2 px-1 py-0.5 rounded text-left transition-colors text-[11px]',
                    active ? 'text-gray-700' : 'text-gray-400'
                  )}
                >
                  <span
                    className="w-4 h-px shrink-0"
                    style={{ backgroundColor: active ? '#6366f1' : '#d1d5db' }}
                  />
                  <span className="flex-1 truncate">{type}</span>
                  {count > 0 && <span className="text-gray-400 text-[10px]">{count}</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
