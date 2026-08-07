import { useMemo } from 'react';
import { ListChecks, CheckCircle2, Circle, XCircle, Loader2 } from 'lucide-react';
import { cn, toTitleCase } from '@/utils';
import type { TraceStep, PlanStepInfo } from '@/types';
import { TOOL_LABELS } from '@/constants/chat';

interface PlanIndicatorProps {
  trace: TraceStep[];
  isStreaming?: boolean;
}

const statusIcon = (status: PlanStepInfo['status'], isActive: boolean) => {
  if (status === 'completed') return <CheckCircle2 size={11} className="text-dark-lime shrink-0" />;
  if (status === 'skipped') return <XCircle size={11} className="text-gray-500 shrink-0" />;
  if (isActive) return <Loader2 size={11} className="shrink-0 text-amber-400 animate-spin" />;
  return <Circle size={11} className="shrink-0 text-gray-600" />;
};

/**
 * During streaming, the plan's step statuses are all "pending" because the
 * backend finalizes them only at the end.  Derive live statuses by matching
 * completed action trace entries against plan steps.
 */
function useLiveSteps(
  planSteps: PlanStepInfo[] | undefined,
  trace: TraceStep[],
  isStreaming: boolean
) {
  return useMemo(() => {
    if (!planSteps) return undefined;
    // When not streaming, trust the backend-provided statuses
    if (!isStreaming) return planSteps;

    // Collect tool names that have a successful observation in the trace
    const completedTools = new Set<string>();
    for (const t of trace) {
      if (t.kind === 'observation' && t.success && t.tool) {
        completedTools.add(t.tool);
      }
    }

    // Tools currently in-progress: have an action but no observation yet
    const activeTools = new Set<string>();
    for (const t of trace) {
      if (t.kind === 'action' && t.tool && !completedTools.has(t.tool)) {
        activeTools.add(t.tool);
      }
    }

    // Check if we have an answer step (meaning synthesize is done)
    const hasAnswer = trace.some((t) => t.kind === 'answer');

    return planSteps.map((step) => {
      if (step.status !== 'pending') return step;
      if (step.action === 'synthesize' && hasAnswer)
        return { ...step, status: 'completed' as const };
      if (completedTools.has(step.action)) return { ...step, status: 'completed' as const };
      return step;
    });
  }, [planSteps, trace, isStreaming]);
}

export default function PlanIndicator({ trace, isStreaming = false }: PlanIndicatorProps) {
  const planStep = trace.find((s) => s.kind === 'plan');
  const liveSteps = useLiveSteps(planStep?.steps, trace, isStreaming);

  if (!planStep) return null;

  // Prefer structured data; fall back to text parsing for old responses
  if (liveSteps && planStep.plan) {
    // Determine the first pending step as the "active" one during streaming
    const firstPendingIdx = isStreaming ? liveSteps.findIndex((s) => s.status === 'pending') : -1;

    return (
      <div className="flex items-start gap-2 py-2 text-xs text-gray-400 mt-2">
        <div className="flex flex-col min-w-0 gap-1">
          <div className="font-medium text-black mb-1">Plan: {planStep.plan}</div>
          {liveSteps.map(({ status, action, purpose, id }, i) => {
            const isActive = isStreaming && i === firstPendingIdx;
            return (
              <div key={id} className="flex items-center gap-1">
                <span className="inline-flex relative top-[0.5px]">
                  {statusIcon(status, isActive)}
                </span>
                <span
                  className={cn(
                    'inline-flex',
                    status === 'completed' && 'line-through text-gray-600',
                    status === 'skipped' && 'line-through text-gray-700'
                  )}
                >
                  <strong className="text-dark-lime">
                    {TOOL_LABELS[action] ?? toTitleCase(action)}
                  </strong>{' '}
                  — {purpose}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  // Legacy: parse from content text
  if (!planStep.content) return null;

  const lines = planStep.content
    .split('\n')
    .map((l) =>
      l
        .replace(/^\d+\.\s*/, '')
        .replace(/^[-•]\s*/, '')
        .trim()
    )
    .filter(Boolean);

  if (!lines.length) return null;

  const actionCount = trace.filter((s) => s.kind === 'action').length;

  return (
    <div className="flex items-start gap-2 px-3 py-2 text-xs text-gray-400 bg-purple-500/5 border border-purple-500/20 rounded-lg mt-2">
      <ListChecks size={14} className="text-purple-400 shrink-0 mt-0.5" />
      <div className="flex flex-col gap-1 min-w-0">
        <span className="font-medium text-purple-400">Plan</span>
        {lines.map((line, i) => {
          const done = i < actionCount;
          return (
            <div key={i} className="flex items-center gap-1.5">
              {done ? (
                <CheckCircle2 size={11} className="text-emerald-400 shrink-0" />
              ) : (
                <Circle
                  size={11}
                  className={cn('shrink-0', i === actionCount ? 'text-amber-400' : 'text-gray-600')}
                />
              )}
              <span className={cn(done && 'line-through text-gray-600')}>{line}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
