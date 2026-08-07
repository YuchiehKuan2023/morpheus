import type { KeyPerformanceIndicator } from '@/components/common/KPI';
import type {
  ClassificationKpi,
  DetectionKpi,
  FilterTab,
  LlmExplanation,
  ProcessGroup,
  SimSpeed,
  SimulationStatus,
} from '@/types/simulation';

export const SIM_SPEED = ['realistic', 'fast', 'demo'] as const;
export const SIM_STAGE = [
  'sent',
  'clean',
  'detected',
  'enriched',
  'labeled',
  'classified',
  'agent_running',
  'complete',
  'failed',
] as const;
export const SIM_FILTER_TAB = ['all', 'anomalies', 'clean', 'in_progress'] as const;
export const SIM_PROCESS_STATUS = ['pending', 'running', 'completed', 'error'] as const;
export const SIM_PROCESS_GROUP = ['inference', 'ai_orchestrator', 'agent_orchestrator'] as const;
export const SIM_EVENT_TYPE = ['clean', 'novel'] as const;
export const AGENT_TYPE = ['forensics', 'investigation', 'remediation'] as const;
export const AGENT_STATUS = ['pending', 'running', 'complete', 'failed', 'skipped'] as const;
export const DETECTION_KPI = ['risk', 'mean', 'score', 'severity'] as const;
export const CLASSIFICATION_KPI = [
  'cause',
  'classifier',
  'category',
  'confidence',
  'retrain',
] as const;

export const SPEEDS: { id: SimSpeed; label: string; description: string }[] = [
  { id: 'realistic', label: 'Realistic', description: '~15 min/event' },
  { id: 'fast', label: 'Fast', description: '~90 s/event' },
  { id: 'demo', label: 'Demo', description: '~15 s/event' },
];

export const TABS: { id: FilterTab; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'anomalies', label: 'Anomalies' },
  { id: 'clean', label: 'Clean' },
  { id: 'in_progress', label: 'In progress' },
];

export const TERMINAL_STAGES = new Set(['complete', 'clean', 'failed', 'labeled']);

/** Event cards per page when the simulation is running. */
export const PAGE_SIZE_RUNNING = 15;

/** Event cards per page when the simulation is idle. */
export const PAGE_SIZE_IDLE = 10;

export const STAGE_LABEL: Record<string, string> = {
  sent: 'Sent',
  clean: 'Clean',
  detected: 'Detected',
  enriched: 'Enriched',
  labeled: 'Labeled',
  classified: 'Classified',
  agent_running: 'Investigating',
  complete: 'Complete',
  failed: 'Failed',
};

export const GROUP_LABELS: Record<ProcessGroup, string> = {
  inference: 'Inference Pipeline',
  ai_orchestrator: 'AI Orchestrator',
  agent_orchestrator: 'Agent Orchestrator',
};

export const PROCESS_LABELS: Record<string, string> = {
  kafka_sent: 'Event published to Kafka',
  dfp_scoring: 'DFP Scoring & AI Enrichment',
  context_enrichment: 'Context Enrichment',
  llm_classification: 'LLM Classification',
  risk_scoring: 'Risk Scoring',
  shap_explanation: 'SHAP Feature Attribution',
  lime_explanation: 'LIME Local Explanation',
  forensics_agent: 'ForensicsAgent',
  investigation_agent: 'InvestigationAgent',
  remediation_agent: 'RemediationAgent',
};

export const GROUP_ORDER: ProcessGroup[] = ['inference', 'ai_orchestrator', 'agent_orchestrator'];

export const DETECTION_KPIS: { [K in DetectionKpi]: KeyPerformanceIndicator } = {
  risk: {
    title: 'Risk Score',
    size: 'sm',
    className: 'no-border no-shadow',
  },
  mean: {
    title: 'Mean Abs Z',
    size: 'sm',
    className: 'no-border no-shadow',
  },
  score: {
    title: 'Anomaly Score',
    size: 'sm',
    className: 'no-border no-shadow',
  },
  severity: {
    title: 'Severity',
    size: 'sm',
    className: 'no-border no-shadow',
  },
};

export const CLASSIFICATION_KPIS: { [K in ClassificationKpi]: KeyPerformanceIndicator } = {
  cause: {
    title: 'Cause',
    size: 'xs',
    className: 'no-border no-shadow',
  },
  classifier: {
    title: 'Classifier',
    size: 'xs',
    className: 'no-border no-shadow',
  },
  category: {
    title: 'Category',
    size: 'xs',
    className: 'no-border no-shadow',
  },
  confidence: {
    title: 'Confidence',
    size: 'xs',
    className: 'no-border no-shadow',
  },
  retrain: {
    title: 'Retrain?',
    size: 'xs',
    className: 'no-border no-shadow',
  },
};

export const VERDICT_CONFIG = {
  true: { label: 'True Anomaly' },
  false: { label: 'False Positive' },
  null: { label: 'Pending Review' },
};

export const LLM_SECTIONS: Array<{ key: keyof LlmExplanation; label: string }> = [
  { key: 'contextAnalysis', label: 'Context Analysis' },
  { key: 'patternAnalysis', label: 'Pattern Analysis' },
  { key: 'riskAssessment', label: 'Risk Assessment' },
  { key: 'recommendations', label: 'Recommendations' },
  { key: 'reasoningProcess', label: 'Reasoning Process' },
];

export const AGENT_KNOWN_KEYS: Record<string, string[]> = {
  forensics: [
    'narrative',
    'attack_chain',
    'entry_point',
    'lateral_movement_detected',
    'confidence',
  ],
  investigation: [
    'pattern_analysis',
    'similar_detections',
    'dominant_root_cause',
    'recurrence_count',
    'recurrence_detected',
    'first_seen',
    'confidence',
  ],
  remediation: ['recommended_actions', 'compliance_flags', 'escalation_required', 'confidence'],
};

export const TYPE_LABEL: Record<string, string> = {
  metric_anomaly: 'Metric Anomaly',
  baseline_mismatch: 'Baseline Mismatch',
  baseline_match: 'Baseline Match',
  anomaly_score: 'Anomaly Score',
  temporal_pattern: 'Temporal Pattern',
  temporal_mismatch: 'Temporal Mismatch',
  historical_pattern: 'Historical Pattern',
  entity_risk: 'Entity Risk',
  physical_impossibility: 'Physical Impossibility',
  insufficient_data: 'Insufficient Data',
};

export const DEFAULT_STATUS: SimulationStatus = {
  running: false,
  run_id: null,
  started_at: null,
  events_sent: 0,
  anomalies_detected: 0,
  clean_count: 0,
  novel_sent: 0,
  active_trackers: 0,
  total_sent: 0,
  total_anomalies: 0,
  total_clean: 0,
};
