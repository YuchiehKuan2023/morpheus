import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Network } from 'lucide-react';
import { Spinner } from '@/components';
import { GraphVisualization, GraphControls } from '@/components/graph';
import type { GraphVizRef } from '@/components/graph';
import { useGraph } from '@/hooks';
import type { GraphNode, NodeLabel } from '@/types';

export default function Graph() {
  const {
    data,
    rawData,
    stats,
    selectedNode,
    nodeDetail,
    loading,
    error,
    filters,
    expandedCount,
    selectNode,
    toggleLabel,
    toggleRelType,
    setSearchQuery,
    focusUser,
    expandNode,
    resetFilters,
  } = useGraph();

  // Add body class so tailwind.css can strip the container's padding/max-width
  useEffect(() => {
    document.body.classList.add('page-graph');
    return () => document.body.classList.remove('page-graph');
  }, []);

  // Measure only the canvas column (not the sidebar)
  const canvasRef = useRef<HTMLDivElement>(null);
  const vizRef = useRef<GraphVizRef | null>(null);
  const [dims, setDims] = useState({ w: 800, h: 600 });

  useLayoutEffect(() => {
    const measure = () => {
      if (canvasRef.current) {
        const rect = canvasRef.current.getBoundingClientRect();
        setDims({ w: Math.floor(rect.width), h: Math.floor(rect.height) });
      }
    };
    measure();
    const ro = new ResizeObserver(measure);
    if (canvasRef.current) ro.observe(canvasRef.current);
    return () => ro.disconnect();
  }, []);

  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      selectNode(selectedNode?.id === node.id ? null : node);
    },
    [selectNode, selectedNode]
  );

  const handleNodeRightClick = useCallback(
    (node: GraphNode) => {
      expandNode(node.id);
    },
    [expandNode]
  );

  const totalNodesDisplay = stats
    ? stats.total_nodes.toLocaleString()
    : rawData.nodes.length.toLocaleString();
  const totalRelsDisplay = stats
    ? stats.total_relationships.toLocaleString()
    : rawData.links.length.toLocaleString();

  return (
    <div
      className="flex flex-col overflow-hidden h-full bg-gray-50"
      onContextMenu={(e) => e.preventDefault()}
    >
      {/* ── Compact header ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 h-12 shrink-0 border-b border-gray-200 bg-white shadow-sm">
        <div className="flex items-center gap-2.5">
          <Network size={16} className="text-(--brand-black) shrink-0" />
          <span className="text-sm font-semibold text-gray-900">
            <strong>Knowledge Graph</strong> - Entity relationships from DFP detections
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs">
          {stats && (
            <>
              <span>
                <span className="text-gray-900 font-semibold">{totalNodesDisplay}</span>{' '}
                <span className="text-gray-400">nodes</span>
              </span>
              <span className="text-gray-300">·</span>
              <span>
                <span className="text-gray-900 font-semibold">{totalRelsDisplay}</span>{' '}
                <span className="text-gray-400">relationships</span>
              </span>
              {filters.focusUserId && (
                <>
                  <span className="text-gray-300">·</span>
                  <button
                    onClick={() => focusUser(null)}
                    className="text-indigo-500 hover:text-indigo-700 transition-colors"
                  >
                    ✕ clear focus
                  </button>
                </>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Body: canvas column + sidebar column ───────────────────────── */}
      <div className="flex-1 flex flex-row overflow-hidden">
        {/* Canvas */}
        <div ref={canvasRef} className="flex-1 relative overflow-hidden">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center z-10 bg-gray-50">
              <div className="flex flex-col items-center gap-3">
                <Spinner />
                <p className="text-sm text-gray-400">Loading graph…</p>
              </div>
            </div>
          )}

          {error && !loading && (
            <div className="absolute inset-0 flex items-center justify-center z-10">
              <p className="text-red-500 text-sm">{error}</p>
            </div>
          )}

          {!loading && !error && (
            <GraphVisualization
              data={data}
              width={dims.w}
              height={dims.h}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
              onNodeRightClick={handleNodeRightClick}
              onBackgroundClick={() => selectNode(null)}
              vizRef={vizRef}
            />
          )}
        </div>

        {/* Sidebar */}
        <div className="w-100 max-w-100 shrink-0 border-l border-gray-200 bg-white overflow-y-auto">
          <GraphControls
            filters={filters}
            stats={stats}
            visibleNodes={data.nodes.length}
            visibleLinks={data.links.length}
            expandedCount={expandedCount}
            vizRef={vizRef}
            selectedNode={selectedNode}
            nodeDetail={nodeDetail}
            onToggleLabel={(label) => toggleLabel(label as NodeLabel)}
            onToggleRelType={toggleRelType}
            onSearchChange={setSearchQuery}
            onReset={resetFilters}
            onDeselectNode={() => selectNode(null)}
            onFocusUser={(uid) => focusUser(uid)}
          />
        </div>
      </div>
    </div>
  );
}
