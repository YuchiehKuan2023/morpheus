import type { TraceStep } from '@/types/chat';

export const CHAT_SESSION_STATUS = ['active', 'archived'] as const;
export const CHAT_MESSAGE_ROLES = ['user', 'assistant'] as const;
export const PLAN_STEP_STATUS = ['pending', 'completed', 'skipped'] as const;
export const TRACE_STEP_KINDS = [
  'thought',
  'action',
  'observation',
  'plan',
  'reflection',
  'answer',
] as const;

export const TOOL_LABELS: Record<string, string> = {
  search_anomalies: 'Anomaly Search',
  get_anomaly_detail: 'Anomaly Detail',
  get_user_profile: 'User Profile',
  get_similar_anomalies: 'Similarity Search',
  get_risk_summary: 'Risk Summary',
  get_top_anomalies: 'Top Anomalies',
  get_investigation: 'Investigation Findings',
  get_neo4j_graph: 'Knowledge Graph',
  get_root_cause_summary: 'Root Cause Analysis',
  semantic_search_anomalies: 'Semantic Search',
  get_anomaly_timeline: 'Timeline',
  get_user_behaviour_baseline: 'User Baseline',
  get_llm_explanations: 'AI Explanations',
  get_dimension_ranking: 'Dimension Ranking',
  query_database: 'Custom Query',
};

export const KIND_CONFIG: Record<TraceStep['kind'], { label: string }> = {
  thought: { label: 'Thought' },
  action: { label: 'Tool Call' },
  observation: { label: 'Observation' },
  plan: { label: 'Plan' },
  reflection: { label: 'Reflection' },
  answer: { label: 'Answer' },
};
