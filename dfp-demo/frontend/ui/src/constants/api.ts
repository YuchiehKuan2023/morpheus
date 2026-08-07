import type { AppApi } from '@/types';

export const DASHBOARD_API = [
  'stats',
  'statsTrend',
  'intradayRhythm',
  'investigationTrend',
  'recentAnomalies',
  'riskDistribution',
  'topUsers',
  'topAnomalies',
  'topRootCauses',
  'activityHeatmap',
  'userMetrics',
  'systemMaturity',
  'platformStats',
  'snapshot',
] as const;
export const ANOMALIES_API = [
  'list',
  'detail',
  'status',
  'investigation',
  'explanation',
  'pipeline',
  'reorchestrate',
  'reorchestrateStream',
] as const;
export const USERS_API = ['list', 'detail', 'profile', 'trend', 'full', 'anomalies'] as const;
export const DETECTIONS_API = ['list'] as const;
export const SIMULATION_API = ['users', 'start', 'stop', 'status', 'sessions', 'stream'] as const;

const v1 = '/api/v1';

export const API = {
  dashboard: {
    stats: `${v1}/dashboard/stats`,
    statsTrend: `${v1}/dashboard/stats-trend`,
    recentAnomalies: `${v1}/dashboard/recent-anomalies`,
    riskDistribution: `${v1}/dashboard/risk-distribution`,
    topUsers: `${v1}/dashboard/top-users`,
    topAnomalies: `${v1}/dashboard/top-anomalies`,
    topRootCauses: `${v1}/dashboard/top-root-causes`,
    activityHeatmap: `${v1}/dashboard/activity-heatmap`,
    intradayRhythm: `${v1}/dashboard/intraday-rhythm`,
    investigationTrend: `${v1}/dashboard/investigation-trend`,
    userMetrics: `${v1}/dashboard/user-metrics`,
    systemMaturity: `${v1}/dashboard/system-maturity`,
    platformStats: `${v1}/dashboard/platform-stats`,
    snapshot: `${v1}/dashboard/snapshot`,
  },
  anomalies: {
    list: (limit?: number) => (limit ? `${v1}/anomalies?limit=${limit}` : `${v1}/anomalies`),
    detail: (id: string) => `${v1}/anomalies/${id}`,
    status: (id: string) => `${v1}/anomalies/${id}/status`,
    investigation: (id: string) => `${v1}/anomalies/${id}/investigation`,
    explanation: (id: string) => `${v1}/anomalies/${id}/explanation`,
    pipeline: (id: string) => `${v1}/anomalies/${id}/pipeline`,
    reorchestrate: (id: string) => `${v1}/anomalies/${id}/reorchestrate`,
    reorchestrateStream: (id: string, sessionId: string) =>
      `${v1}/anomalies/${id}/reorchestrate/stream?session_id=${sessionId}`,
    assign: (id: string) => `${v1}/anomalies/${id}/assign`,
    review: (id: string) => `${v1}/anomalies/${id}/review`,
    myQueue: (limit?: number) =>
      limit ? `${v1}/anomalies/queue/my?limit=${limit}` : `${v1}/anomalies/queue/my`,
    unassigned: (limit?: number) =>
      limit
        ? `${v1}/anomalies/queue/unassigned?limit=${limit}`
        : `${v1}/anomalies/queue/unassigned`,
  },
  users: {
    list: `${v1}/users`,
    detail: (username: string) => `${v1}/users/${username}`,
    profile: (username: string) => `${v1}/users/${username}/profile`,
    trend: (username: string, days?: number) =>
      days ? `${v1}/users/${username}/trend?days=${days}` : `${v1}/users/${username}/trend`,
    full: (username: string) => `${v1}/users/${username}/full`,
    anomalies: (
      username: string,
      opts?: {
        page?: number;
        pageSize?: number;
        sortBy?: string;
        sortDir?: string;
        rootCause?: string;
        subCategory?: string;
      }
    ) => {
      const params = new URLSearchParams();
      if (opts?.page) params.set('page', String(opts.page));
      if (opts?.pageSize) params.set('page_size', String(opts.pageSize));
      if (opts?.sortBy) params.set('sort_by', opts.sortBy);
      if (opts?.sortDir) params.set('sort_dir', opts.sortDir);
      if (opts?.rootCause) params.set('root_cause', opts.rootCause);
      if (opts?.subCategory) params.set('sub_category', opts.subCategory);
      const qs = params.toString();
      return qs ? `${v1}/users/${username}/anomalies?${qs}` : `${v1}/users/${username}/anomalies`;
    },
  },
  chat: {},
  detections: {
    list: (limit?: number) => (limit ? `${v1}/detections?limit=${limit}` : `${v1}/detections`),
  },
  simulation: {
    users: `${v1}/simulation/users`,
    start: `${v1}/simulation/start`,
    stop: `${v1}/simulation/stop`,
    status: `${v1}/simulation/status`,
    sessions: (opts?: { runId?: string; page?: number; pageSize?: number; tab?: string }) => {
      const params = new URLSearchParams();
      if (opts?.runId) params.set('run_id', opts.runId);
      if (opts?.page) params.set('page', String(opts.page));
      if (opts?.pageSize) params.set('page_size', String(opts.pageSize));
      if (opts?.tab && opts.tab !== 'all') params.set('tab', opts.tab);
      const qs = params.toString();
      return qs ? `${v1}/simulation/sessions?${qs}` : `${v1}/simulation/sessions`;
    },
    stream: (runId?: string) =>
      runId ? `${v1}/simulation/stream?run_id=${runId}` : `${v1}/simulation/stream`,
  },
  graph: {
    stats: `${v1}/graph/stats`,
    data: (limit?: number, nodeTypes?: string) => {
      const params = new URLSearchParams();
      if (limit) params.set('limit', String(limit));
      if (nodeTypes) params.set('node_types', nodeTypes);
      const qs = params.toString();
      return qs ? `${v1}/graph/data?${qs}` : `${v1}/graph/data`;
    },
    node: (id: string) => `${v1}/graph/node/${id}`,
    neighbours: (id: string, depth?: number) =>
      depth
        ? `${v1}/graph/node/${id}/neighbours?depth=${depth}`
        : `${v1}/graph/node/${id}/neighbours`,
    userSubgraph: (userId: string) => `${v1}/graph/user/${encodeURIComponent(userId)}/subgraph`,
    clusters: (minDetections?: number, limit?: number) => {
      const params = new URLSearchParams();
      if (minDetections) params.set('min_detections', String(minDetections));
      if (limit) params.set('limit', String(limit));
      const qs = params.toString();
      return qs ? `${v1}/graph/anomaly-clusters?${qs}` : `${v1}/graph/anomaly-clusters`;
    },
  },
  health: '/api/health',
  auth: {
    login: `${v1}/auth/login`,
    me: `${v1}/auth/me`,
    logout: `${v1}/auth/logout`,
  },
  notifications: {
    list: `${v1}/notifications`,
    unreadCount: `${v1}/notifications/unread-count`,
    seen: (id: number) => `${v1}/notifications/${id}/seen`,
    seenAll: `${v1}/notifications/seen-all`,
  },
  forecast: {
    data: (periods?: number) => (periods ? `${v1}/forecast?periods=${periods}` : `${v1}/forecast`),
    summary: `${v1}/forecast/summary`,
    retrain: (force?: boolean) =>
      force ? `${v1}/forecast/retrain?force=true` : `${v1}/forecast/retrain`,
  },
} satisfies AppApi;
