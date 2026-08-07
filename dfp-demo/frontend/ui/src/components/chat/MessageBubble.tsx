import { cn, formatDateTime } from '@/utils';
import { Bot, User } from 'lucide-react';
import type { ChatMessage } from '@/types';
import ReasoningTrace from './ReasoningTrace';
import PlanIndicator from './PlanIndicator';
import ClarificationRequest from './ClarificationRequest';
import { Confidence, Content, Intent, Sources, Tools } from '@/components/chat';

interface MessageBubbleProps {
  message: ChatMessage;
  onClarificationSelect?: (answer: string) => void;
  onFollowupSelect?: (question: string) => void;
  isLatest?: boolean;
}

export default function MessageBubble({
  message,
  onClarificationSelect,
  onFollowupSelect,
  isLatest,
}: MessageBubbleProps) {
  const {
    role,
    tools_used: toolsUsed,
    reasoning_trace: trace,
    intent,
    sources,
    created_at: createdAt,
    confidence,
    content,
    suggested_followups: followups,
  } = message;

  const isUser = role === 'user';
  const hasTools = !isUser && !!toolsUsed && toolsUsed.length > 0;
  const hasTrace = !isUser && !!trace && trace.length > 0;
  const hasConfidence =
    confidence !== undefined && !Number.isNaN(confidence) && confidence !== null;
  const hasSources = sources && sources.length > 0;
  const hasIntent = !!intent;
  const hasMetadata = !isUser && (hasIntent || hasTools || hasSources || hasConfidence || hasTrace);
  const isStreaming = !isUser && isLatest && !content && !!trace && trace.length > 0;

  return (
    <div className={cn('flex gap-3 px-4 py-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      {/* Bubble */}
      <div
        className={cn(
          'flex flex-col gap-1',
          isUser ? 'items-end' : 'items-start min-w-3xl max-w-3xl'
        )}
      >
        <div
          className={cn(
            'flex items-center gap-2 mb-1',
            isUser ? 'flex-row-reverse' : 'flex-row ml-8'
          )}
        >
          {/* Avatar */}
          <div
            className={cn(
              'shrink-0 w-8 h-8 rounded-full inline-flex items-center justify-center text-white',
              isUser ? 'bg-gray-300' : 'bg-dark-lime'
            )}
          >
            {isUser ? <User size={14} /> : <Bot size={14} />}
          </div>
          {/* Timestamp */}
          <span className="text-[10px] text-gray-600 px-1">
            {isUser ? 'You · ' : 'AI Assistant · '}
            {formatDateTime(createdAt)}
          </span>
        </div>

        {/* ── Metadata panel ── Intent / Sources / Confidence */}
        <div className={cn('ai-response-bubble', !isUser && 'ai')}>
          {hasMetadata && (
            <div className="w-full mb-4 flex flex-col gap-1.5 text-xs text-gray-500">
              <Intent {...{ intent }} />
              <Sources {...{ sources }} />
              <Tools {...{ toolsUsed, isUser }} />
              <Confidence {...{ confidence }} />
              {/* Reasoning trace + plan */}
              {hasTrace && (
                <>
                  <PlanIndicator trace={trace!} isStreaming={isStreaming} />
                  <ReasoningTrace trace={trace!} isStreaming={isStreaming} />
                  <ClarificationRequest
                    trace={trace!}
                    onSelect={onClarificationSelect ?? (() => {})}
                  />
                </>
              )}
            </div>
          )}

          {/* Content */}
          <div
            className={
              isUser
                ? 'rounded-2xl px-4 py-3 text-sm leading-relaxed bg-gray-300 text-black rounded-tr-sm'
                : ''
            }
          >
            {isUser ? (
              <p className="whitespace-pre-wrap">{content}</p>
            ) : (
              <div className="leading-relaxed text-muted-foreground text-sm">
                {content && <div className="separator -ml-3 -mr-3 mb-4 mt-5" />}
                <Content {...{ content }} />
              </div>
            )}
          </div>

          {/* Suggested follow-ups */}
          {!isUser && isLatest && followups && followups.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-gray-200/50">
              {followups.map((q, i) => (
                <button
                  key={i}
                  onClick={() => onFollowupSelect?.(q)}
                  className="text-xs px-3 py-1.5 rounded-full border border-purple-500/30 text-purple-400 hover:bg-purple-500/10 hover:border-purple-500/50 transition-colors cursor-pointer"
                >
                  {q}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
