import { DATE_FORMAT } from '@/constants';
import { format, isValid, parseISO } from 'date-fns';

/**
 * Shared formatting utilities
 */

/**
 * Format a GBP value with M/K suffix for display.
 * e.g. 1_500_000 → "£1.5M", 25_000 → "£25K", 999 → "£999"
 */
export function formatGbp(value: number): string {
  const MILLION = 1_000_000;
  const THOUSAND = 1_000;

  if (value >= MILLION) {
    return `£${(value / MILLION).toFixed(1)}M`;
  }

  if (value >= THOUSAND) {
    const rounded = Math.round(value / THOUSAND);
    if (rounded >= 1000) {
      return `£${(value / MILLION).toFixed(1)}M`;
    }
    return `£${rounded}K`;
  }

  return `£${value.toFixed(0)}`;
}

export const formatTextWithCurrency = (text: string): string => {
  // Match currency patterns like £1,234.56789 or £1234.56789
  return text.replace(/£([\d,]+\.?\d*)/g, (match, number) => {
    const numValue = parseFloat(number.replace(/,/g, ''));
    if (isNaN(numValue)) return match;
    return formatCurrency(numValue);
  });
};

export const formatCurrency = (value: number): string => {
  return new Intl.NumberFormat('en-GB', {
    style: 'currency',
    currency: 'GBP',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
};

export const formatNumber = (value: number): string => {
  return new Intl.NumberFormat('en-GB', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
};

/**
 * Format any ISO date string using the app-wide DATE_FORMAT.
 * Returns '—' for null/undefined/invalid values.
 */
export function formatDate(ts: string | null | undefined): string {
  if (!ts) return '—';
  const date = parseISO(ts);
  return isValid(date) ? format(date, DATE_FORMAT) : '—';
}

export function formatRelative(ts: string): string {
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export function formatDisplayDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

export const formatDateTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString('en-GB', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—';

export const fmtDay = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });

export const fmtPct = (v: number | null) => (v != null ? `${v.toFixed(1)}%` : '—');
export const fmtConf = (v: number | null) => (v != null ? (v * 100).toFixed(1) + '%' : '—');
export const fmtHours = (v: number | null) => {
  if (v == null) return '—';
  if (v < 1) return `${Math.round(v * 60)}m`;
  return `${v.toFixed(1)}h`;
};
