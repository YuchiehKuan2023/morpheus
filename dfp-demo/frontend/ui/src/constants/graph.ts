import type { GraphFilters } from '@/types/graph';

export const NODE_LABELS = [
  'User',
  'Detection',
  'Application',
  'Device',
  'Browser',
  'OperatingSystem',
  'IPAddress',
  'ClientApp',
  'Location',
  'Unknown',
] as const;

export const ALL_LABELS = new Set(NODE_LABELS.filter((l) => l !== 'Unknown')) as Set<
  GraphFilters['visibleLabels'] extends Set<infer T> ? T : never
>;

export const DEFAULT_FILTERS: GraphFilters = {
  visibleLabels: ALL_LABELS,
  searchQuery: '',
  focusUserId: null,
  limit: 500,
  hiddenRelTypes: new Set<string>(),
};
