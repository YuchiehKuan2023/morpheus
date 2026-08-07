export interface AnalystNotification {
  id: number;
  anomalyId: string | null;
  type: string;
  title: string;
  message: string | null;
  seenAt: string | null;
  createdAt: string | null;
}
