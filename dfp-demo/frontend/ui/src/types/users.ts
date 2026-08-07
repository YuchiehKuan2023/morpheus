import type { USER_STATUS, USER_TAB_TYPES } from '@/constants/users';
import type { TopUser, UserDetail, UserMetrics } from '@/types';

export type UserStatus = (typeof USER_STATUS)[number];
export type TabType = (typeof USER_TAB_TYPES)[number];

export interface User {
  username: string;
  totalEvents: number;
  anomalyCount: number;
  lastSeen: string;
  riskScore: number;
  status: UserStatus;
}

export interface UserProfile {
  username: string;
  model_version: string;
  last_training: string;
  event_count: number;
  mean_features: Record<string, number>;
  std_features: Record<string, number>;
}

export interface UsersState {
  items: User[];
  selectedUser: User | null;
  searchQuery: string;
}

export interface GaugeDef {
  label: string;
  key: keyof UserMetrics;
  max: number;
  /** override display value formatting */
  format?: (v: number) => string;
  color: string;
}

export type UserDetailState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: UserDetail }
  | { status: 'error'; message: string };

export type UserDetailAction =
  | { type: 'reset' }
  | { type: 'success'; payload: UserDetail }
  | { type: 'not_found' }
  | { type: 'error' };

export interface UserTabProps {
  detail: UserDetail;
  type: TabType;
  loading?: boolean;
}

export interface UserDetailProps {
  user: TopUser | null;
  open: boolean;
  onClose: () => void;
}
