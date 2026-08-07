import { useState } from 'react';
import { ChevronDown, ChevronRight, CheckCircle2, XCircle } from 'lucide-react';
import { toTitleCase } from '@/utils';
import type { TraceStep } from '@/types';
import { KIND_CONFIG, TOOL_LABELS } from '@/constants/chat';
import { Badge } from '..';

interface ReasoningTraceProps {
  trace: TraceStep[];
}

const statusIcon = (status: boolean) => {
  return status ? (
    <CheckCircle2 size={11} className="text-dark-lime shrink-0" />
  ) : (
    <XCircle size={11} className="text-gray-500 shrink-0" />
  );
};

function StepRow({ step }: { step: TraceStep; index: number }) {
  const cfg = KIND_CONFIG[step.kind] ?? KIND_CONFIG.thought;

  if (step.kind === 'plan') return null;

  return (
    <div className="flex items-center gap-2 py-1.5 text-xs">
      <div className="flex-1 items-start gap-1">
        <div className="flex">
          <span className="font-medium">
            {cfg.label}
            {step.kind !== 'answer' && ':'}{' '}
          </span>
          <span className="inline-flex items-center">
            {step.tool && (
              <span className="text-bold ml-1.5">
                {TOOL_LABELS[step.tool]
                  ? `Get ${TOOL_LABELS[step.tool]}`
                  : toTitleCase(step.tool.replace(/_/g, ' '))}
              </span>
            )}
            {step.elapsed_ms != null && step.elapsed_ms > 0 && (
              <span className="text-gray-500 ml-1.5">({step.elapsed_ms}ms)</span>
            )}
            {step.success != null && (
              <span className="ml-1.5 relative mt-0.5">{statusIcon(step.success)}</span>
            )}
          </span>
        </div>
        <div className="flex flex-col">
          {step.content && <span className="text-gray-400 wrap-break-word">{step.content}</span>}
        </div>
      </div>
    </div>
  );
}

interface ReasoningTraceExtProps extends ReasoningTraceProps {
  isStreaming?: boolean;
}

export default function ReasoningTrace({ trace, isStreaming = false }: ReasoningTraceExtProps) {
  const [manualToggle, setManualToggle] = useState<boolean | null>(null);

  // Auto-open while streaming, auto-close when done.
  // User's manual toggle takes precedence.
  const open = manualToggle ?? isStreaming;

  const handleToggle = () => setManualToggle(!open);

  if (!trace.length) return null;

  const reasoning = trace.filter((step) => step.kind !== 'plan');
  const stepCount = reasoning.length;
  const toolSteps = reasoning.filter((s) => s.kind === 'action');

  return (
    <div className="mt-2 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={handleToggle}
        className="w-full flex items-center gap-2 py-2 text-sm text-black"
      >
        <span className="flex gap-1 items-center">
          <span>Reasoning:</span>
          <Badge>
            {stepCount} step{stepCount !== 1 && 's'}
          </Badge>
          {toolSteps.length > 0 && (
            <Badge>
              {toolSteps.length} tool call{toolSteps.length !== 1 ? 's' : ''}
            </Badge>
          )}
        </span>
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>

      {open && (
        <div className="pb-2">
          {reasoning.map((step, i) => (
            <StepRow key={i} step={step} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
