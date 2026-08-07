import type {
  AGENT_STATUS,
  AGENT_TYPE,
  CLASSIFICATION_KPI,
  DETECTION_KPI,
  SIM_EVENT_TYPE,
  SIM_FILTER_TAB,
  SIM_PROCESS_GROUP,
  SIM_PROCESS_STATUS,
  SIM_SPEED,
  SIM_STAGE,
} from '@/constants/simulation';
import type { Severity } from '@/types/anomalies';

export type SimStage = (typeof SIM_STAGE)[number];
export type FilterTab = (typeof SIM_FILTER_TAB)[number];
export type ProcessStatus = (typeof SIM_PROCESS_STATUS)[number];
export type ProcessGroup = (typeof SIM_PROCESS_GROUP)[number];
export type SimSpeed = (typeof SIM_SPEED)[number];
export type SimEventType = (typeof SIM_EVENT_TYPE)[number];
export type AgentType = (typeof AGENT_TYPE)[number];
export type AgentStatus = (typeof AGENT_STATUS)[number];
export type DetectionKpi = (typeof DETECTION_KPI)[number];
export type ClassificationKpi = (typeof CLASSIFICATION_KPI)[number];

export interface SimProcessEntry {
  group: ProcessGroup;
  process: string;
  status: ProcessStatus;
  ts: string | null;
  detail: string | null;
}

export interface SimulationSession {
  session_id: string;
  run_id: string;
  user_id: string;
  event_type: SimEventType;
  scenario: string | null;
  sent_at: string;
  updated_at: string;
  stage: SimStage;
  anomaly_id: string | null;
  anomaly_score: number | null;
  severity: string | null;
  root_cause: string | null;
  risk_score: number | null;
  investigation_id: string | null;
  investigation_status: string | null;
  completed_at: string | null;
  stages_log: SimProcessEntry[];
}

/** Counts returned in every paginated sessions response. */
export interface SessionCounts {
  all: number;
  anomalies: number;
  clean: number;
  in_progress: number;
}

/** Paginated response from GET /simulation/sessions. */
export interface PaginatedSessions {
  items: SimulationSession[];
  counts: SessionCounts;
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export interface SimulationStatus {
  running: boolean;
  run_id: string | null;
  started_at: string | null;
  events_sent: number;
  anomalies_detected: number;
  clean_count: number;
  novel_sent: number;
  active_trackers: number;
  total_sent: number;
  total_anomalies: number;
  total_clean: number;
}

export interface SimulationUser {
  user_id: string;
  display_name: string;
  avatar_initials: string;
  avatar_color: string;
  avatar_url?: string;
  anomaly_count: number;
  total_events: number;
}

export interface MonitoredUser {
  displayName: string | null;
  firstName: string | null;
  lastName: string | null;
  email: string | null;
  jobTitle: string | null;
  department: string | null;
  company: string | null;
  seniority: string | null;
  userRole: string | null;
  avatarUrl: string | null;
  avatarInitials: string | null;
  avatarColor: string | null;
  city: string | null;
  country: string | null;
}

export interface EvidenceItem {
  type: string;
  description: string;
  metric?: string;
  value?: string;
  z_score?: number | null;
  severity?: Severity | string;
  category?: string;
}

export interface LlmExplanation {
  contextAnalysis: string | null;
  patternAnalysis: string | null;
  riskAssessment: string | null;
  recommendations: string | null;
  reasoningProcess: string | null;
  evidenceSummary: EvidenceItem[] | null;
  entitiesReferenced: unknown[] | null;
  llmSeverityLevel: string | null;
  llmConfidence: number | null;
  anomalyClassification: {
    positive: boolean | null;
    threat_types: string[] | null;
  } | null;
  modelUsed: string | null;
  completionTokens: number | null;
  createdAt: string | null;
}

export interface AgentFinding {
  agentType: AgentType | string;
  status: AgentStatus | string;
  result: Record<string, unknown> | null;
  latencyMs: number | null;
  completedAt: string | null;
}

export interface AssignedAnalyst {
  userId: string;
  displayName: string;
  firstName: string | null;
  lastName: string | null;
  email: string;
  role: string;
  level: number | null;
  avatarUrl: string | null;
  avatarInitials: string | null;
  avatarColor: string | null;
}

export interface AnomalyInvestigation {
  investigationId: string;
  triggeredAt: string | null;
  completedAt: string | null;
  status: string;
  severityAtTrigger: string | null;
  agentsInvoked: string[];
  confidenceScore: number | null;
  overallRecommendation: string | null;
  assignedAnalyst: AssignedAnalyst | null;
  findings: AgentFinding[];
}

export interface ShapEntry {
  feature: string;
  label: string;
  contribution: number;
  value: number;
}

export interface LimeWeight {
  feature: string;
  label: string;
  weight: number;
  value: number;
}

export interface AnomalyExplanation {
  anomalyId: string;
  shap: {
    baseValue: number | null;
    prediction: number | null;
    shapUsed: boolean;
    topDrivers: ShapEntry[];
    topMitigators: ShapEntry[];
    shapValues: Record<string, number>;
  } | null;
  lime: {
    limeWeights: LimeWeight[];
  } | null;
  confidence: {
    confidence: number;
    components: { risk: number; dfp: number; llm: number };
  } | null;
}

export interface AnomalyDetail {
  anomalyId: string;
  userId: string;
  user: MonitoredUser | null;
  timestamp: string;
  anomalyScore: number;
  meanAbsZ: number | null;
  severity: string | null;
  rootCause: string | null;
  subCategory: string | null;
  riskScore: number | null;
  isAnomaly: boolean | null;
  status: string | null;
  classifiedBy: string | null;
  classificationConfidence: number | null;
  validationConfidence: number | null;
  validationReasoning: string | null;
  dfpRetrainStatus: string | null;
  assignedTo: number | null;
  analystVerdict: string | null;
  analystNotes: string | null;
  reviewedBy: number | null;
  reviewedAt: string | null;
  resolutionNotes: string | null;
  resolvedAt: string | null;
  originalEvent: Record<string, unknown> | null;
  rawDetection: Record<string, unknown> | null;
  aiEnrichment: Record<string, unknown> | null;
  createdAt: string | null;
  classifiedAt: string | null;
  validatedBy: string | null;
  processed: boolean;
  llmExplanation: LlmExplanation | null;
  investigation: AnomalyInvestigation | null;
}

export type DetailState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: AnomalyDetail }
  | { status: 'error'; message: string };

export type DetailAction =
  | { type: 'fetch' }
  | { type: 'success'; payload: AnomalyDetail }
  | { type: 'error' };
