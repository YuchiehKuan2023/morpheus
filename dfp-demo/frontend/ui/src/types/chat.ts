import type {
  CHAT_MESSAGE_ROLES,
  CHAT_SESSION_STATUS,
  PLAN_STEP_STATUS,
  TRACE_STEP_KINDS,
} from '@/constants/chat';

export type ChatSessionStatus = (typeof CHAT_SESSION_STATUS)[number];
export type ChatMessageRole = (typeof CHAT_MESSAGE_ROLES)[number];
export type PlanStepStatus = (typeof PLAN_STEP_STATUS)[number];
export type TraceStepKind = (typeof TRACE_STEP_KINDS)[number];

export interface ChatSession {
  id: number;
  title: string;
  status: ChatSessionStatus;
  is_pinned: boolean;
  user_id: number | null;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

export type ChatSessionMessage = {
  role: ChatMessageRole;
  content: string;
  created_at: string;
  tools_used?: string[];
  intent?: string;
  sources?: string[];
};

export interface ChatSessionExport {
  title: string;
  created_at: string;
  updated_at: string;
  messages: ChatSessionMessage[];
}

export interface PlanStepInfo {
  id: number;
  action: string;
  purpose: string;
  status: PlanStepStatus;
}

export interface TraceStep {
  kind: TraceStepKind;
  content?: string;
  tool?: string;
  params?: Record<string, unknown>;
  success?: boolean;
  elapsed_ms?: number;
  // Structured plan data (kind === 'plan')
  plan?: string;
  steps?: PlanStepInfo[];
}

export interface ChatMessage {
  id: number;
  session_id: number;
  role: ChatMessageRole;
  content: string;
  tools_used?: string[];
  created_at: string;
  intent?: string;
  confidence?: number;
  sources?: string[];
  reasoning_trace?: TraceStep[];
  suggested_followups?: string[];
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatMessage[];
}

export interface QueryResponse {
  answer: string;
  tools_used: string[];
  session_id: number;
  suggested_followups?: string[];
  intent?: string;
  confidence?: number;
  sources?: string[];
  reasoning_trace?: TraceStep[];
  steps?: number;
}

export interface AgentMetrics {
  total_queries: number;
  avg_steps: number;
  max_steps: number;
  tool_distribution: Record<string, number>;
  avg_tool_latency: Record<string, number>;
}

export interface SuggestionsResponse {
  suggestions: string[];
}
