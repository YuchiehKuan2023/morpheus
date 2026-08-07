import {
  ArrayList,
  Badge,
  DialogSection,
  ObjectGrid,
  ObjectList,
  SimilarDetectionsCarousel,
} from '@/components';
import { AGENT_KNOWN_KEYS } from '@/constants/simulation';
import type { AgentFinding } from '@/types/simulation';
import { AttackChainTimeline, type AttackChainItem } from './AttackChainTimeline';
import { formatScalar, isObjectArray, isPlainObject } from '@/utils';
import { type FC } from 'react';

interface Props {
  finding: AgentFinding;
}

function ResultValue({ fieldKey, value }: { fieldKey: string; value: unknown }) {
  const k = fieldKey.replace(/_/g, ' ');

  if (typeof value === 'boolean') {
    return (
      <div className="result-row">
        <span className="result-row--title">{k}</span>:{' '}
        <Badge variant={value ? 'lime' : undefined}>{value ? 'Yes' : 'No'}</Badge>
      </div>
    );
  }

  if (typeof value === 'string') {
    return (
      <div className="result-row">
        <span className="result-row--title">{k}</span>:{' '}
        <span className="result-row--value">{formatScalar(k, value)}</span>
      </div>
    );
  }

  if (typeof value === 'number') {
    return (
      <div className="result-row">
        <span className="result-row--title">{k}</span>: {formatScalar(fieldKey, value)}
      </div>
    );
  }

  if (fieldKey === 'attack_chain' && isObjectArray(value)) {
    return <AttackChainTimeline items={value as unknown as AttackChainItem[]} />;
  }

  if (fieldKey === 'similar_detections' && isObjectArray(value)) {
    return <SimilarDetectionsCarousel items={value} />;
  }

  if (isObjectArray(value)) {
    return <ObjectList {...{ fieldKey }} items={value} />;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return <p className="text-sm text-muted-foreground">—</p>;

    return <ArrayList value={value} k={k} />;
  }

  if (isPlainObject(value)) {
    return <ObjectGrid item={value} />;
  }

  return <p className="text-sm text-muted-foreground">{String(value)}</p>;
}

export const AgentCard: FC<Props> = (props) => {
  const { finding } = props;

  const knownKeys = AGENT_KNOWN_KEYS[finding.agentType] ?? [];
  const result = finding.result;
  const knownEntries: [string, unknown][] = [];
  const unknownEntries: [string, unknown][] = [];

  if (result) {
    for (const [k, v] of Object.entries(result)) {
      if (v == null || v === '' || (Array.isArray(v) && v.length === 0)) continue;
      if (knownKeys.includes(k)) knownEntries.push([k, v]);
      else unknownEntries.push([k, v]);
    }
    // Sort knownEntries by the order defined in knownKeys
    knownEntries.sort(([a], [b]) => knownKeys.indexOf(a) - knownKeys.indexOf(b));
  }

  return (
    <DialogSection
      title={
        <span className="flex items-center gap-1.5">
          <span className="capitalize">{finding.agentType} Agent</span>
        </span>
      }
      actions={
        <>
          {finding.latencyMs != null && <Badge>Duration: {finding.latencyMs}ms</Badge>}
          <Badge {...(finding.status.toLowerCase() === 'complete' ? { variant: 'lime' } : {})}>
            {finding.status}
          </Badge>
        </>
      }
      description={
        !result || finding.status === 'skipped' ? (
          <p className="text-sm text-muted-foreground">No findings available.</p>
        ) : (
          <div className="space-y-3">
            {[...knownEntries, ...unknownEntries].map(([k, v]) => {
              return (
                <div key={k}>
                  <ResultValue fieldKey={k} value={v} />
                </div>
              );
            })}
          </div>
        )
      }
      separator
    />
  );
};
