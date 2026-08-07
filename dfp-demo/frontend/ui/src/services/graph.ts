import { API, API_BASE_URL } from '@/constants';
import type { AnomalyCluster, GraphData, GraphStats, NodeDetail } from '@/types';

async function fetchJson<T>(endpoint: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    throw new Error(`Graph API error ${response.status}: ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const graphApi = {
  getStats: (): Promise<GraphStats> => fetchJson(API.graph.stats),

  getData: (limit?: number, nodeTypes?: string): Promise<GraphData> =>
    fetchJson(API.graph.data(limit, nodeTypes)),

  getNode: (id: string): Promise<NodeDetail> => fetchJson(API.graph.node(id)),

  getNeighbours: (id: string, depth?: number): Promise<GraphData> =>
    fetchJson(API.graph.neighbours(id, depth)),

  getUserSubgraph: (userId: string): Promise<GraphData> =>
    fetchJson(API.graph.userSubgraph(userId)),

  getClusters: (minDetections?: number, limit?: number): Promise<AnomalyCluster[]> =>
    fetchJson(API.graph.clusters(minDetections, limit)),
};
