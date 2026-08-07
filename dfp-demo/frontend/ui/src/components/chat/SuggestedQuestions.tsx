import { Sparkles } from 'lucide-react';
import { cn } from '@/utils';

interface SuggestedQuestionsProps {
  questions: string[];
  onSelect: (q: string) => void;
}

export default function SuggestedQuestions({ questions, onSelect }: SuggestedQuestionsProps) {
  return (
    <div className="flex flex-col items-center gap-6 px-4 py-8 max-w-2xl mx-auto w-full">
      <div className="flex flex-col items-center gap-2 text-center">
        <div className="w-12 h-12 rounded-full bg-pale-lime flex items-center justify-center">
          <Sparkles size={22} className="text-black" />
        </div>
        <h2 className="text-lg font-semibold text-gray-800">DFP Intelligence Assistant</h2>
        <p className="text-sm text-gray-500 max-w-sm">
          Ask anything about anomalies, user behaviour, risk levels, or investigation findings. The
          AI determines the right data sources automatically.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full">
        {questions.map((q) => (
          <button
            key={q}
            onClick={() => onSelect(q)}
            className={cn(
              'text-left text-xs text-gray-700 px-3 py-2.5 rounded-lg',
              'bg-pale-lime',
              'transition-colors leading-snug cursor-pointer'
            )}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
