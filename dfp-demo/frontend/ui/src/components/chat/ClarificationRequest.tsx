import { HelpCircle } from 'lucide-react';
import type { TraceStep } from '@/types';

interface ClarificationRequestProps {
  trace: TraceStep[];
  onSelect: (answer: string) => void;
}

/**
 * Renders a styled clarification card when the agent used
 * the `ask_clarification` tool during its reasoning.
 * Shows the question and clickable option buttons.
 */
export default function ClarificationRequest({ trace, onSelect }: ClarificationRequestProps) {
  // Find an ask_clarification observation that has options
  const clarification = trace.find(
    (s) =>
      s.kind === 'observation' && s.tool === 'ask_clarification' && s.success === true && s.content
  );
  if (!clarification?.content) return null;

  // Parse options from the observation content (JSON-like format from the tool)
  let question = '';
  let options: string[] = [];

  try {
    // The observation content is a summary like: "[ask_clarification] → dict with 3 keys"
    // The actual data is in params — but the trace doesn't carry raw output.
    // Instead, look for the action step's params which has question + options.
    const actionStep = trace.find(
      (s) => s.kind === 'action' && s.tool === 'ask_clarification' && s.params
    );
    if (actionStep?.params) {
      question = (actionStep.params.question as string) ?? '';
      options = (actionStep.params.options as string[]) ?? [];
    }
  } catch {
    // Fallback: use the observation content as the question
    question = clarification.content;
  }

  if (!question) return null;

  return (
    <div className="flex items-start gap-2.5 px-4 py-3 mt-2 text-sm bg-amber-500/5 border border-amber-500/20 rounded-lg">
      <HelpCircle size={16} className="text-amber-400 shrink-0 mt-0.5" />
      <div className="flex flex-col gap-2 min-w-0">
        <p className="text-gray-300 font-medium">{question}</p>
        {options.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {options.map((opt) => (
              <button
                key={opt}
                type="button"
                onClick={() => onSelect(opt)}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 hover:border-amber-500/50 transition-colors cursor-pointer"
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
