/**
 * Utilities for rendering agent finding result values in a human-readable way.
 *
 * Agent results are arbitrary JSONB blobs. This module provides type-safe
 * helpers so AgentCard never falls back to raw JSON.stringify output.
 */

import { ISO_DATE_RE, PERCENT_KEYS, SKIP_IN_OBJECT } from '@/constants/shared';

/** Format a leaf scalar value (string | number | boolean | null). */
export function formatScalar(key: string, value: unknown): string {
  if (value == null) return '—';

  if (typeof value === 'boolean') return value ? 'Yes' : 'No';

  if (typeof value === 'number') {
    // Render 0–1 floats as percentages for known metric keys
    if (PERCENT_KEYS.has(key.toLowerCase()) && value >= 0 && value <= 1) {
      return `${(value * 100).toFixed(1)}%`;
    }

    return String(value);
  }

  if (typeof value === 'string') {
    if (ISO_DATE_RE.test(value)) {
      return new Date(value).toLocaleString('en-GB', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    }

    return value;
  }

  return String(value);
}

/** True when a value is a plain JS object (not array, not null). */
export function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** True when every element of the array is a plain object. */
export function isObjectArray(v: unknown): v is Record<string, unknown>[] {
  return Array.isArray(v) && v.length > 0 && v.every(isPlainObject);
}

/**
 * Returns the display label for an object-array item.
 * Prefers `action` → `event_type` → `root_cause` → `type` as a summary title.
 */
export function getItemTitle(item: Record<string, unknown>): string | null {
  for (const key of ['action', 'event_type', 'root_cause', 'type']) {
    if (typeof item[key] === 'string') return item[key] as string;
  }
  return null;
}

/**
 * Returns the entries of an object suitable for rendering, omitting null/empty
 * values and keys already used as the item title.
 */
export function objectEntries(
  item: Record<string, unknown>,
  skipTitle = true
): [string, unknown][] {
  return Object.entries(item).filter(([k, v]) => {
    if (v == null || v === '') return false;
    if (skipTitle && SKIP_IN_OBJECT.has(k)) return false;
    return true;
  });
}
