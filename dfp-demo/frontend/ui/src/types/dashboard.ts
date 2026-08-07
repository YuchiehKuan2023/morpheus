import type { KeyPerformanceIndicator } from '@/components/common/KPI';
import type { AnomalyStatus, Severity } from './anomalies';
import type { Stats } from './stats';
import {
  DASHBOARD_COMPONENTS,
  DASHBOARD_SECTIONS,
  SECTION_COMPONENT_MAPPING,
  STAT_TYPES,
  SYSTEM_MATURITY_LEVELS,
} from '@/constants/dashboard';

export type SystemMaturityLevel = (typeof SYSTEM_MATURITY_LEVELS)[number];
export type StatType = (typeof STAT_TYPES)[number];
export type DashboardStatType = Severity | StatType;
export type DashboardComponent = (typeof DASHBOARD_COMPONENTS)[number];
export type DashboardSection = (typeof DASHBOARD_SECTIONS)[number];

export type RiskDistributionData = {
  label: Severity;
  value: number;
  active?: boolean;
};

type RootCauseMeta = {
  Anomalies: TopRootCause['anomaly_count'];
  'Affected users': TopRootCause['affected_users'];
  'Avg score': TopRootCause['avg_anomaly_score'];
  'Avg risk score': TopRootCause['avg_risk_score'];
  Critical: TopRootCause['critical_count'];
  High: TopRootCause['high_count'];
  Medium: TopRootCause['medium_count'];
  'Last seen': TopRootCause['last_seen_at'];
};

export type RootCauseData = {
  label: TopRootCause['root_cause'];
  value: TopRootCause['anomaly_count'];
  active: boolean;
  meta: RootCauseMeta;
};

// ── Dashboard layout descriptors ──────────────────────────────────────────────

export interface SectionDescriptor {
  title: string;
  subtitle: string;
}

export interface ComponentDescriptor {
  title: string;
  description: string;
  tooltip: string;
}

/**
 * Strongly-typed dashboard layout. Each section carries its own metadata and a
 * `components` record whose keys are *exactly* the components assigned to that
 * section in `SECTION_COMPONENT_MAPPING` — nothing more, nothing less.
 */
export type DashboardLayout = {
  [S in DashboardSection]: {
    section: SectionDescriptor;
    components: {
      [C in (typeof SECTION_COMPONENT_MAPPING)[S][number]]: ComponentDescriptor;
    };
  };
};

export type DashboardStats = {
  [K in DashboardStatType]: KeyPerformanceIndicator;
};

export type UsersAnomalyStats = {
  [K in AnomalyStatus]: KeyPerformanceIndicator;
};

export interface InvestigationTrendDay {
  day: string;
  triggered: number;
  completed: number;
  failed: number;
  pending: number;
  completion_rate: number | null;
  avg_confidence: number | null;
  avg_duration_hours: number | null;
}

export interface DashboardState {
  stats: Stats | null;
  statsTrend: StatsTrend | null;
  intradayRhythm: IntradayRhythmCell[];
  investigationTrend: InvestigationTrendDay[];
  recentAnomalies: DashboardRecentAnomaly[];
  riskDistribution: RiskDistribution;
  topAnomalies: TopAnomaly[];
  topUsers: TopUser[];
  topRootCauses: TopRootCause[];
  activityHeatmap: HeatmapDay[];
  userMetrics: UserMetrics | null;
  systemMaturity: SystemMaturity | null;
  loading: boolean;
}

/** Shape returned by the consolidated GET /dashboard/snapshot endpoint. */
export interface DashboardSnapshot {
  stats: Stats;
  statsTrend: StatsTrend;
  recentAnomalies: DashboardRecentAnomaly[];
  riskDistribution: RiskDistribution;
  topAnomalies: TopAnomaly[];
  topUsers: TopUser[];
  topRootCauses: TopRootCause[];
  activityHeatmap: HeatmapDay[];
  userMetrics: UserMetrics;
  systemMaturity: SystemMaturity;
  intradayRhythm: IntradayRhythmCell[];
  investigationTrend: InvestigationTrendDay[];
  platformStats: PlatformStats;
}

export interface MaturityBucket {
  count: number;
  pct: number;
}

export interface SystemMaturity {
  score: number;
  level: SystemMaturityLevel;
  total: number;
  distribution: {
    resilient: MaturityBucket;
    managed: MaturityBucket;
    exposed: MaturityBucket;
  };
}

export interface HeatmapDay {
  date: string;
  count: number;
  max_score: number | null;
  confirmed_count: number;
  false_positive_count: number;
  new_count: number;
}

export interface UserTrendPoint {
  /** ISO date "YYYY-MM-DD" */
  bucket: string;
  count: number;
  avg_score: number;
}

export interface IntradayRhythmCell {
  /** 0=Mon … 6=Sun */
  dow: number;
  /** 0–23 */
  hour: number;
  count: number;
  avg_score: number;
}

export interface StatsTrendEntry {
  current: number;
  previous: number;
  /** Positive = up, negative = down. */
  delta_pct: number;
}

export interface StatsTrend {
  critical: StatsTrendEntry;
  high: StatsTrendEntry;
  medium: StatsTrendEntry;
  low: StatsTrendEntry;
}

export interface TopRootCause {
  root_cause: string;
  anomaly_count: number;
  affected_users: number;
  avg_anomaly_score: number;
  avg_risk_score: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  last_seen_at: string | null;
}

// ── Dedicated dashboard API response types ────────────────────────────────────

export interface DashboardRecentAnomaly {
  anomaly_id: string;
  user_id: string;
  timestamp: string;
  anomaly_score: number;
  severity: string;
  root_cause: string | null;
  sub_category: string | null;
  risk_score: number | null;
  status: string;
  original_event: Record<string, unknown> | null;
  // joined from monitored_users
  display_name: string | null;
  avatar_color: string | null;
  avatar_initials: string | null;
  avatar_url: string | null;
  company: string | null;
  department: string | null;
  devices: unknown;
  apps: unknown;
  all_locations: unknown;
}

export type RiskDistribution = { [S in Severity | 'total']: number };

export interface UserMetrics {
  /** % of monitored users with at least one anomaly */
  exposureRate: number;
  /** % of affected users with at least one CRITICAL anomaly */
  criticalRatio: number;
  /** Avg anomaly score across all enriched_anomalies (0-10 scale) */
  avgRiskScore: number;
  /** % of anomalies with status = resolved */
  resolutionRate: number;
  /** Avg hours between consecutive anomalies per user */
  mtbaHours: number;
}

export interface TopUserAnomaly {
  anomaly_id: string;
  anomaly_score: number;
  severity: string;
  root_cause: string | null;
  sub_category: string | null;
  risk_score: number | null;
  status: string;
  timestamp: string;
  ai_enrichment: Record<string, unknown> | null;
}

export interface UserLocation {
  city: string;
  country: string;
  lat: number;
  lon: number;
  frequency: number;
}

export interface UserDevice {
  name: string;
  count: number;
}

export interface UserApp {
  app: string;
  count: number;
}

export interface TopUser {
  id: number;
  username: string;
  user_guid: string | null;
  display_name: string | null;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  company: string | null;
  department: string | null;
  user_role: string | null;
  job_title: string | null;
  seniority: string | null;
  primary_location_city: string | null;
  primary_location_country: string | null;
  home_location_lat: number | null;
  home_location_lon: number | null;
  all_locations: UserLocation[] | null;
  primary_os: string | null;
  primary_browser: string | null;
  primary_device: string | null;
  devices: UserDevice[] | null;
  apps: UserApp[] | null;
  work_hours_start: number | null;
  work_hours_end: number | null;
  active_days: string[] | null;
  total_events: number | null;
  avatar_color: string | null;
  avatar_initials: string | null;
  avatar_url: string | null;
  corp_vpn: boolean | null;
  created_at: string | null;
  updated_at: string | null;
  // computed aggregates
  anomaly_count: number;
  last_anomaly_at: string | null;
  avg_anomaly_score: number;
  critical_count: number;
  top_anomalies: TopUserAnomaly[] | null;
}

export interface TopAnomaly {
  anomaly_id: string;
  user_id: string;
  timestamp: string;
  anomaly_score: number;
  severity: string;
  root_cause: string | null;
  sub_category: string | null;
  risk_score: number | null;
  is_anomaly: boolean | null;
  status: string;
  original_event: Record<string, unknown> | null;
  ai_enrichment: Record<string, unknown> | null;
  created_at: string | null;
  // joined from monitored_users
  display_name: string | null;
  avatar_color: string | null;
  avatar_initials: string | null;
  avatar_url: string | null;
  department: string | null;
  company: string | null;
}

// ── User Detail (full dialog data) ───────────────────────────────────────────

export interface TrimmedGraphContext {
  detected_ips: string[];
  detected_devices: string[];
  detected_browsers: string[];
  detected_locations: string[];
  detected_client_apps: string[];
  detected_applications: string[];
  detected_operating_systems: string[];
  recent_detections: number;
  related_anomalies_count: number;
}

export interface GraphContextCombined {
  detected_ips: string[];
  detected_devices: string[];
  detected_browsers: string[];
  detected_locations: string[];
  detected_client_apps: string[];
  detected_applications: string[];
  detected_operating_systems: string[];
  detected_location_coords: Record<string, { lat: number; lon: number }>;
  total_recent_detections: number;
}

export interface UserDetailAnomaly {
  anomaly_id: string;
  anomaly_score: number;
  severity: string;
  root_cause: string | null;
  sub_category: string | null;
  risk_score: number | null;
  status: string;
  timestamp: string;
  similar_detections_count: number;
  graph_context: TrimmedGraphContext | null;
}

export interface UserDetail extends Omit<TopUser, 'top_anomalies'> {
  all_anomalies: UserDetailAnomaly[];
  trend: UserTrendPoint[];
  user_baseline: Record<string, unknown> | null;
  graph_context_combined: GraphContextCombined | null;
}

export interface FilterOption {
  value: string;
  count: number;
}

export interface PaginatedUserAnomalies {
  items: UserDetailAnomaly[];
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
  filters: {
    rootCauses: FilterOption[];
    subCategories: FilterOption[];
  };
}

export interface PlatformStats {
  monitoredUsers: number;
  totalDetections: number;
  truePositives: number;
  labeledRecords: number;
  rootCauseCount: number;
  totalInvestigations: number;
  completedInvestigations: number;
  totalFindings: number;
  qdrantDocuments: number;
  qdrantCollections: number;
  migrationCount: number;
  usersWithAnomalies: number;
}

// ── Forecast types ─────────────────────────────────────────────────────────

export interface ForecastHistoricalPoint {
  date: string;
  count: number;
}

export interface ForecastPredictionPoint {
  date: string;
  yhat: number;
  yhat_lower: number;
  yhat_upper: number;
}

export interface ForecastMeta {
  trained_at?: string;
  training_days?: number;
  date_range?: [string, string];
  total_anomalies?: number;
  data_mode?: 'all' | 'real_only';
  error?: string;
}

export interface ForecastData {
  historical: ForecastHistoricalPoint[];
  forecast: ForecastPredictionPoint[];
  meta: ForecastMeta;
}

export interface ForecastSummary {
  data: {
    total_anomalies: number;
    real_anomalies: number;
    synthetic_anomalies: number;
    earliest: string | null;
    latest: string | null;
    user_count: number;
    ready_for_real_only: boolean;
  };
  model: {
    status: string;
    started_at: string;
    completed_at: string | null;
    anomalies_at_retrain: number;
    duration_seconds: number | null;
  } | null;
}
