import type { AnomaliesState } from '@/types';

export const ANOMALIES_INITIAL_STATE: AnomaliesState = {
  items: [],
  filter: {
    severity: [],
    status: [],
    searchQuery: '',
  },
  selectedAnomaly: null,
};

export const SEVERITIES = ['critical', 'high', 'medium', 'low'] as const;
export const ANOMALY_STATUSES = ['new', 'pending', 'resolved'] as const;

export const ANOMALY_DETAILS_TABS = [
  { id: 'detection', label: 'Detection' },
  { id: 'ai', label: 'Analysis' },
  { id: 'investigation', label: 'Investigation' },
  { id: 'explanation', label: 'Explanation' },
  { id: 'pipeline', label: 'Pipeline' },
  { id: 'raw', label: 'Data' },
  { id: 'review', label: 'Review' },
];

export const VERDICT_OPTIONS = [
  { value: 'confirmed', label: 'Confirmed Anomaly' },
  { value: 'false_positive', label: 'False Positive' },
  { value: 'escalated', label: 'Escalate' },
  { value: 'dismissed', label: 'Dismiss' },
];
