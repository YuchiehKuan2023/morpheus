import type { NODE_LABELS } from '@/constants/graph';

// Node labels from the DFP Neo4j schema
export type NodeLabel = (typeof NODE_LABELS)[number];

export interface GraphNode {
  id: string;
  label: NodeLabel;
  name: string;
  // User props
  user_id?: string;
  // Detection props
  detection_id?: string;
  timestamp?: string;
  // Application props
  type?: string;
  // Device / Browser / OS props
  // IPAddress props
  address?: string;
  // Location props
  city?: string;
  country?: string;
  // Allow any extra property from Neo4j
  [key: string]: unknown;
}

export interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  type: string;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export interface GraphStats {
  node_counts: Record<string, number>;
  relationship_counts: Record<string, number>;
  total_nodes: number;
  total_relationships: number;
}

export interface NodeDetail {
  id: string;
  labels: string[];
  properties: Record<string, unknown>;
}

export interface AnomalyCluster {
  user_neo_id: string;
  user_id: string;
  detection_count: number;
}

export interface GraphState {
  data: GraphData;
  stats: GraphStats | null;
  selectedNode: GraphNode | null;
  nodeDetail: NodeDetail | null;
  clusters: AnomalyCluster[];
  loading: boolean;
  statsLoading: boolean;
  error: string | null;
  filters: GraphFilters;
}

export interface GraphFilters {
  visibleLabels: Set<NodeLabel>;
  searchQuery: string;
  focusUserId: string | null;
  limit: number;
  hiddenRelTypes: Set<string>;
}
