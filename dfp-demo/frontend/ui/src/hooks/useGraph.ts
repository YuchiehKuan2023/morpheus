import { useCallback, useEffect, useRef, useState } from 'react';
import { graphApi } from '@/services/graph';
import type {
  AnomalyCluster,
  GraphData,
  GraphFilters,
  GraphNode,
  GraphStats,
  NodeDetail,
} from '@/types';
import { DEFAULT_FILTERS } from '@/constants/graph';

export default function useGraph() {
  const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
  const [filteredData, setFilteredData] = useState<GraphData>({ nodes: [], links: [] });
  const [expandedCount, setExpandedCount] = useState(0);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [clusters, setClusters] = useState<AnomalyCluster[]>([]);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [nodeDetail, setNodeDetail] = useState<NodeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<GraphFilters>(DEFAULT_FILTERS);

  // Keep a ref to avoid stale-closure issues in applyFilters
  const dataRef = useRef(data);
  dataRef.current = data;

  // ── Load graph data ──────────────────────────────────────────────────────
  const loadData = useCallback(
    async (newFilters?: Partial<GraphFilters>) => {
      const merged: GraphFilters = { ...filters, ...newFilters };
      setLoading(true);
      setError(null);
      try {
        let result: GraphData;
        if (merged.focusUserId) {
          result = await graphApi.getUserSubgraph(merged.focusUserId);
        } else {
          result = await graphApi.getData(merged.limit);
        }
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load graph');
      } finally {
        setLoading(false);
      }
    },
    [filters]
  );

  // ── Load stats (separate, lighter call) ─────────────────────────────────
  const loadStats = useCallback(async () => {
    setStatsLoading(true);
    try {
      const [s, c] = await Promise.all([graphApi.getStats(), graphApi.getClusters(3, 10)]);
      setStats(s);
      setClusters(c);
    } catch {
      // Stats are non-critical
    } finally {
      setStatsLoading(false);
    }
  }, []);

  // ── Apply label/search filters client-side ───────────────────────────────
  useEffect(() => {
    const { visibleLabels, searchQuery } = filters;
    const q = searchQuery.toLowerCase();

    const visibleNodes = data.nodes.filter((n) => {
      if (!visibleLabels.has(n.label)) return false;
      if (q && !String(n.name).toLowerCase().includes(q)) return false;
      return true;
    });

    const visibleIds = new Set(visibleNodes.map((n) => n.id));
    const visibleLinks = data.links.filter((l) => {
      if (filters.hiddenRelTypes.has(l.type)) return false;
      return (
        visibleIds.has(typeof l.source === 'string' ? l.source : (l.source as GraphNode).id) &&
        visibleIds.has(typeof l.target === 'string' ? l.target : (l.target as GraphNode).id)
      );
    });

    // Build the set of nodes that have at least one visible link.
    // Isolated nodes (no edges) float far from the main cluster due to
    // the repulsion force having nothing to counteract it.
    // When a search is active we keep all matching nodes so the user can
    // still find an isolated node by name.
    const connectedIds = new Set<string>();
    visibleLinks.forEach((l) => {
      connectedIds.add(typeof l.source === 'string' ? l.source : (l.source as GraphNode).id);
      connectedIds.add(typeof l.target === 'string' ? l.target : (l.target as GraphNode).id);
    });
    const finalNodes = filters.searchQuery
      ? visibleNodes
      : visibleNodes.filter((n) => connectedIds.has(n.id));

    setFilteredData({ nodes: finalNodes, links: visibleLinks });
  }, [data, filters]);

  // ── Initial load ────────────────────────────────────────────────────────
  useEffect(() => {
    loadData();
    loadStats();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Node selection ───────────────────────────────────────────────────────
  const selectNode = useCallback(async (node: GraphNode | null) => {
    setSelectedNode(node);
    setNodeDetail(null);
    if (!node) return;
    try {
      const detail = await graphApi.getNode(node.id);
      setNodeDetail(detail);
    } catch {
      // Detail panel just shows nothing
    }
  }, []);

  // ── Filter helpers ───────────────────────────────────────────────────────
  const toggleLabel = useCallback(
    (label: GraphFilters['visibleLabels'] extends Set<infer T> ? T : never) => {
      setFilters((prev) => {
        const next = new Set(prev.visibleLabels);
        if (next.has(label)) {
          next.delete(label);
        } else {
          next.add(label);
        }
        return { ...prev, visibleLabels: next };
      });
    },
    []
  );

  const setSearchQuery = useCallback((q: string) => {
    setFilters((prev) => ({ ...prev, searchQuery: q }));
  }, []);

  const focusUser = useCallback(
    (userId: string | null) => {
      const newFilters: Partial<GraphFilters> = { focusUserId: userId };
      setFilters((prev) => ({ ...prev, ...newFilters }));
      loadData(newFilters);
    },
    [loadData]
  );

  const resetFilters = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
    setExpandedCount(0);
    loadData(DEFAULT_FILTERS);
  }, [loadData]);

  const toggleRelType = useCallback((type: string) => {
    setFilters((prev) => {
      const next = new Set(prev.hiddenRelTypes);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return { ...prev, hiddenRelTypes: next };
    });
  }, []);

  const expandNode = useCallback(async (nodeId: string) => {
    try {
      const neighbours = await graphApi.getNeighbours(nodeId, 1);
      setData((prev) => {
        const existingIds = new Set(prev.nodes.map((n) => n.id));
        const existingLinks = new Set(
          prev.links.map((l) => {
            const s = typeof l.source === 'string' ? l.source : (l.source as GraphNode).id;
            const t = typeof l.target === 'string' ? l.target : (l.target as GraphNode).id;
            return `${s}-${t}-${l.type}`;
          })
        );
        const newNodes = neighbours.nodes.filter((n) => !existingIds.has(n.id));
        const newLinks = neighbours.links.filter(
          (l) => !existingLinks.has(`${l.source}-${l.target}-${l.type}`)
        );
        if (newNodes.length === 0 && newLinks.length === 0) return prev;
        setExpandedCount((c) => c + 1);
        return {
          nodes: [...prev.nodes, ...newNodes],
          links: [...prev.links, ...newLinks],
        };
      });
    } catch {
      // silent — expand is best-effort
    }
  }, []);

  return {
    data: filteredData,
    rawData: data,
    stats,
    statsLoading,
    clusters,
    selectedNode,
    nodeDetail,
    loading,
    error,
    filters,
    selectNode,
    toggleLabel,
    toggleRelType,
    setSearchQuery,
    focusUser,
    expandNode,
    expandedCount,
    resetFilters,
    reload: loadData,
  };
}
