import type { GaugeDef, UsersState } from '@/types';

export const USERS_INITIAL_STATE: UsersState = {
  items: [],
  selectedUser: null,
  searchQuery: '',
};

export const USER_STATUS = ['normal', 'suspicious', 'critical'] as const;
export const USER_TAB_TYPES = ['details', 'anomalies', 'baseline', 'detections'] as const;

export const ANOMALIES_TAB_SORT_OPTIONS = [
  { value: 'timestamp', label: 'Date' },
  { value: 'severity', label: 'Severity' },
  { value: 'risk_score', label: 'Risk Score' },
  { value: 'anomaly_score', label: 'Anomaly Score' },
] as const;

// ─── Fleet-wide metric gauge ───────────────────────────────────────────────

export const GAUGE_R = 28;
export const GAUGE_CX = 36;
export const GAUGE_CY = 36;
export const SEMI_CIRC = Math.PI * GAUGE_R;
export const GAUGE_PATH = `M ${GAUGE_CX - GAUGE_R} ${GAUGE_CY} A ${GAUGE_R} ${GAUGE_R} 0 0 1 ${GAUGE_CX + GAUGE_R} ${GAUGE_CY}`;

export const GAUGES: GaugeDef[] = [
  {
    label: 'Exposure Rate',
    key: 'exposureRate',
    max: 100,
    format: (v) => `${v.toFixed(0)}%`,
    color: 'var(--brand-dark-lime)',
  },
  {
    label: 'Critical Users',
    key: 'criticalRatio',
    max: 100,
    format: (v) => `${v.toFixed(0)}%`,
    color: 'var(--brand-dark-lime)',
  },
  {
    label: 'Average Risk',
    key: 'avgRiskScore',
    max: 10,
    format: (v) => v.toFixed(1),
    color: 'var(--brand-dark-lime)',
  },
  {
    label: 'Resolved',
    key: 'resolutionRate',
    max: 100,
    format: (v) => `${v.toFixed(0)}%`,
    color: 'var(--brand-dark-lime)',
  },
  {
    label: 'MTBA (h)',
    key: 'mtbaHours',
    max: 24,
    format: (v) => (v < 1 ? `${(v * 60).toFixed(0)}m` : `${v.toFixed(1)}h`),
    color: 'var(--brand-dark-lime)',
  },
];

export const DIALOG_TABS = [
  { id: 'details', label: 'Details' },
  { id: 'anomalies', label: 'Anomalies' },
  { id: 'baseline', label: 'Baseline' },
  { id: 'detections', label: 'Detections' },
];

export const ENTITY_GROUPS: Array<{ key: string; label: string }> = [
  { key: 'ips', label: 'Known IPs' },
  { key: 'devices', label: 'Known Devices' },
  { key: 'browsers', label: 'Known Browsers' },
  { key: 'locations', label: 'Known Locations' },
  { key: 'apps', label: 'Known Applications' },
  { key: 'client_apps', label: 'Known Client Apps' },
  { key: 'operating_systems', label: 'Known Operating Systems' },
];

export const fieldClass = [
  'glass-card',
  'glass-card--xs',
  'no-border',
  'no-shadow',
  'focus:outline-none',
  'focus:ring-0',
  'text-xs',
  'rounded-md!',
].join(' ');

export const resetBtnClass = [
  'cursor-pointer',
  'dark',
  'dfp-btn',
  'gap-1',
  'glass-card',
  'glass-card--xs',
  'inline-flex',
  'items-center',
  'no-border',
  'no-shadow',
  'p-[0.65rem]!',
  'rounded-md!',
  'text-muted-foreground',
].join(' ');
