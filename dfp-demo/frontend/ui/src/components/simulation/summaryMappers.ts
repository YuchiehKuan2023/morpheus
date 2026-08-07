import type { AnomalyDetail, SimulationSession } from '@/types/simulation';

/** Normalized shape consumed by Summary — callers map from their source type. */
export interface SummaryData {
  rootCause: string | null;
  severity: string | null;
  anomalyScore: number | null;
  riskScore: number | null;
  investigationStatus: string | null;
}

export function fromSession(s: SimulationSession): SummaryData {
  return {
    rootCause: s.root_cause,
    severity: s.severity,
    anomalyScore: s.anomaly_score,
    riskScore: s.risk_score,
    investigationStatus: s.investigation_status,
  };
}

export function fromDetail(d: AnomalyDetail): SummaryData {
  return {
    rootCause: d.rootCause,
    severity: d.severity,
    anomalyScore: d.anomalyScore,
    riskScore: d.riskScore,
    investigationStatus: d.investigation?.status ?? d.status,
  };
}
