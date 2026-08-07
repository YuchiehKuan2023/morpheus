import type { KeyboardEvent, RefObject } from 'react';
import { ArrowUp, Loader2 } from 'lucide-react';
import { cn } from '@/utils';

interface ChatInputProps {
  value: string;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading: boolean;
  disabled?: boolean;
  placeholder?: string;
}

export default function ChatInput({
  value,
  onChange,
  textareaRef,
  onSubmit,
  loading,
  disabled,
  placeholder = 'Ask about anomalies, users, risk levels, investigations…',
}: ChatInputProps) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!loading && !disabled && value.trim()) onSubmit();
      }}
      className="flex items-end gap-2 p-3 border-t border-gray-200 bg-white/80 backdrop-blur-sm"
    >
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!loading && !disabled && value.trim()) onSubmit();
          }
        }}
        disabled={loading || disabled}
        placeholder={placeholder}
        className={cn(
          'flex-1 resize-none rounded-xl px-4 py-3 text-sm text-gray-900',
          'bg-white border border-gray-200 placeholder-gray-400',
          'focus:outline-none focus:ring-1 outline-none',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          'max-h-50 overflow-y-auto glass-card glass-card--xs no-border no-shadow'
        )}
      />
      <button
        type="submit"
        disabled={loading || disabled || !value.trim()}
        className={cn(
          'shrink-0 w-10 h-10 rounded-xl flex items-center justify-center',
          'bg-dark-lime text-white transition-colors',
          'disabled:bg-gray-100 disabled:text-gray-400 disabled:cursor-not-allowed cursor-pointer'
        )}
        aria-label="Send message"
      >
        {loading ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={16} />}
      </button>
    </form>
  );
}
