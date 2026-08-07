import type { GraphStats } from '@/types/graph';
import type { PlatformStats } from '@/types/dashboard';
import type { LucideIcon } from 'lucide-react';

export type { GraphStats };
export type { PlatformStats };

export interface ModelDetail {
  icon: LucideIcon;
  label: string;
  value: string;
}

export interface AIModel {
  title: string;
  description: string;
  subtitle: string;
  icon: LucideIcon;
  details: ModelDetail[];
}

export interface Tool {
  name: string;
  description: string;
  source: string;
}

export interface Capability {
  name: string;
  description: string;
  icon: LucideIcon;
  color: string;
  models: AIModel[];
  tools?: Tool[];
}

export interface PlatformOverviewProps {
  graphStats?: GraphStats | null;
}
