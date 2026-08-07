import type { AnomalyStatus } from './anomalies';

export type AnomaliesStats = {
  critical: number;
  high: number;
  medium: number;
  low: number;
  new: number;
  resolved: number;
  pending: number;
};

export interface Stats {
  totalUsers: number;
  totalEvents: number;
  totalAnomalies: number;
  activeUsers: number;
  anomalies: AnomaliesStats;
  avgAnomalyScore: number;
}

export type AnomaliesStatusStats = Pick<AnomaliesStats, AnomalyStatus>;
