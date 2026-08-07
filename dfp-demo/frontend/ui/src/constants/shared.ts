import {
  IAndroid,
  IApple,
  IChrome,
  IEdge,
  IFirefox,
  IGlobe,
  ISafari,
  ITux,
  IWindows,
} from '@/components';
import type { PageHeaderConfig, SvgIcon } from '@/types';

// Empty string → relative URLs → Vite proxy forwards /api/* to localhost:8001 in dev.
// Set VITE_API_URL only when deploying to a remote host.
export const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/** Single source of truth for all displayed dates in the app. */
export const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}T[\d:.]+Z?$/;
export const PERCENT_KEYS = new Set(['confidence', 'similarity', 'score', 'probability']);
/** Keys to skip when rendering an object's key-value pairs. */
export const SKIP_IN_OBJECT = new Set(['action', 'event_type']); // these appear as the title
export const DATE_FORMAT = 'dd MMM yyyy, HH:mm';
export const PAGES = ['dashboard', 'anomalies', 'users', 'chat'] as const;
export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
export const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

export const PAGE_HEADER: PageHeaderConfig = {
  dashboard: {
    title: 'Dashboard',
    description: 'Live threat intelligence and anomaly monitoring across all users',
  },
  anomalies: {
    title: 'Anomalies',
    description: 'Detailed view of all detected anomalies with filtering and search',
  },
  users: {
    title: 'Users',
    description: 'Comprehensive list of monitored users with activity summaries',
  },
  chat: {
    title: 'Conversational AI',
    description: 'Experiment with our AI assistant to investigate anomalies and get insights',
  },
} as const;

export const BROWSER_ICON_MAP: Array<[string, SvgIcon]> = [
  ['chrome', IChrome],
  ['chromeos', IChrome],
  ['firefox', IFirefox],
  ['safari', ISafari],
  ['edge', IEdge],
  ['brave', IGlobe],
  ['opera', IGlobe],
];

export const OS_ICON_MAP: Array<[string, SvgIcon]> = [
  ['windows', IWindows],
  ['android', IAndroid],
  ['ubuntu', ITux],
  ['linux', ITux],
  ['chromeos', IChrome],
  ['mac', IApple],
  ['ios', IApple],
  ['iphone', IApple],
  ['ipad', IApple],
  ['apple', IApple],
];
