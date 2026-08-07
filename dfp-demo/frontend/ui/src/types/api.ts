import type {
  ANOMALIES_API,
  DASHBOARD_API,
  DETECTIONS_API,
  SIMULATION_API,
  USERS_API,
} from '@/constants';
import type { Page } from './shared';

// ─── Key unions derived directly from the tuple constants ──────────────────
export type DashboardApiKey = (typeof DASHBOARD_API)[number];
export type AnomaliesApiKey = (typeof ANOMALIES_API)[number];
export type UsersApiKey = (typeof USERS_API)[number];
export type DetectionsApiKey = (typeof DETECTIONS_API)[number];
export type SimulationApiKey = (typeof SIMULATION_API)[number];

// ─── Per-page value shapes, mapped over the derived key unions ─────────────
// Adding/removing a key in the constant array above forces a shape update here.

type DashboardApiShape = {
  [K in DashboardApiKey]: string;
};

type AnomaliesApiShape = {
  [K in AnomaliesApiKey]: K extends 'list'
    ? (limit?: number) => string
    : K extends 'detail'
      ? (id: string) => string
      : K extends 'status'
        ? (id: string) => string
        : K extends 'investigation'
          ? (id: string) => string
          : K extends 'explanation'
            ? (id: string) => string
            : K extends 'pipeline'
              ? (id: string) => string
              : K extends 'reorchestrate'
                ? (id: string) => string
                : K extends 'reorchestrateStream'
                  ? (id: string, sessionId: string) => string
                  : never;
} & {
  assign: (id: string) => string;
  review: (id: string) => string;
  myQueue: (limit?: number) => string;
  unassigned: (limit?: number) => string;
};

type UsersApiShape = {
  [K in UsersApiKey]: K extends 'list'
    ? string
    : K extends 'detail'
      ? (username: string) => string
      : K extends 'profile'
        ? (username: string) => string
        : K extends 'trend'
          ? (username: string, days?: number) => string
          : K extends 'full'
            ? (username: string) => string
            : K extends 'anomalies'
              ? (
                  username: string,
                  opts?: {
                    page?: number;
                    pageSize?: number;
                    sortBy?: string;
                    sortDir?: string;
                    rootCause?: string;
                    subCategory?: string;
                  }
                ) => string
              : never;
};

type DetectionsApiShape = {
  [K in DetectionsApiKey]: K extends 'list' ? (limit?: number) => string : never;
};

type SimulationApiShape = {
  users: string;
  start: string;
  stop: string;
  status: string;
  sessions: (opts?: { runId?: string; page?: number; pageSize?: number; tab?: string }) => string;
  stream: (runId?: string) => string;
};

// ─── Page → shape registry ─────────────────────────────────────────────────
type PageApiShapeMap = {
  dashboard: DashboardApiShape;
  anomalies: AnomaliesApiShape;
  users: UsersApiShape;
  chat: Record<string, never>;
};

// ─── Final composed type ───────────────────────────────────────────────────
export type AppApi = { [P in Page]: PageApiShapeMap[P] } & {
  detections: DetectionsApiShape;
  simulation: SimulationApiShape;
  graph: GraphApiShape;
  auth: AuthApiShape;
  notifications: NotificationsApiShape;
  forecast: ForecastApiShape;
  health: string;
};

type GraphApiShape = {
  stats: string;
  data: (limit?: number, nodeTypes?: string) => string;
  node: (id: string) => string;
  neighbours: (id: string, depth?: number) => string;
  userSubgraph: (userId: string) => string;
  clusters: (minDetections?: number, limit?: number) => string;
};

type AuthApiShape = {
  login: string;
  me: string;
  logout: string;
};

type NotificationsApiShape = {
  list: string;
  unreadCount: string;
  seen: (id: number) => string;
  seenAll: string;
};

type ForecastApiShape = {
  data: (periods?: number) => string;
  summary: string;
  retrain: (force?: boolean) => string;
};
