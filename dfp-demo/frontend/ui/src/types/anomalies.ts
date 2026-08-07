import type { ANOMALY_STATUSES, SEVERITIES } from '@/constants';

export type Severity = (typeof SEVERITIES)[number];
export type AnomalyStatus = (typeof ANOMALY_STATUSES)[number];

export interface Anomaly {
  id: string;
  username: string;
  timestamp: string;
  anomalyScore: number;
  eventType: string;
  details: Record<string, unknown>;
  severity: Severity;
  status: AnomalyStatus;
  rootCause?: string | null;
  subCategory?: string | null;
  riskScore?: number | null;
  isAnomaly?: boolean | null;
  aiEnrichment?: Record<string, unknown> | null;
  originalEvent?: Record<string, unknown> | null;
  createdAt?: string | null;
}

export interface Detection {
  username: string;
  timestamp: string;
  anomaly_score: number;
  reconstruction_loss: number;
  feature_anomalies: Record<string, number>;
  event_data: Record<string, unknown>;
}

export interface AnomaliesState {
  items: Anomaly[];
  filter: {
    severity: string[];
    status: string[];
    searchQuery: string;
  };
  selectedAnomaly: Anomaly | null;
}
