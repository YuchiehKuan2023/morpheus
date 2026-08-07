import { BotMessageSquare, Loader2 } from 'lucide-react';
import { ChatInput, ChatSidebar, MessageBubble, SuggestedQuestions } from '@/components/chat';
import { useConversationalAi } from '@/hooks';

export default function Chat() {
  const conversationalAi = useConversationalAi();

  const { showEmpty, messagesEndRef, textareaRef } = conversationalAi.data;
  const {
    sessions,
    archivedSessions,
    activeSessionId,
    loadingSessions,
    messages,
    loadingMessages,
    input,
    sending,
    suggestions,
    setInput,
  } = conversationalAi.state;
  const {
    handleNewSession,
    handleSelectSession,
    handleDeleteSession,
    handleArchiveSession,
    handleUnarchiveSession,
    handleRenameSession,
    handleExportSession,
    handleSubmit,
    handleSuggestionSelect,
  } = conversationalAi.handlers;

  return (
    <div className="flex glass-card glass-card--xs chat-container p-0!">
      {/* Sidebar */}
      <ChatSidebar
        sessions={sessions}
        archivedSessions={archivedSessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
        onArchiveSession={handleArchiveSession}
        onUnarchiveSession={handleUnarchiveSession}
        onRenameSession={handleRenameSession}
        onExportSession={handleExportSession}
        loadingSessions={loadingSessions}
      />

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Messages / empty state (scrollable) */}
        <div className="flex-1 overflow-y-auto mt-0.75">
          {loadingMessages ? (
            <div className="flex items-center justify-center h-full text-gray-400">
              <Loader2 size={22} className="animate-spin" />
            </div>
          ) : showEmpty ? (
            <div className="flex items-center justify-center h-full">
              <SuggestedQuestions questions={suggestions} onSelect={handleSuggestionSelect} />
            </div>
          ) : (
            <div className="py-2">
              <div className="flex flex-col">
                {messages.map((msg, i) => (
                  <MessageBubble
                    key={msg.id}
                    message={msg}
                    isLatest={i === messages.length - 1}
                    onFollowupSelect={handleSuggestionSelect}
                  />
                ))}
              </div>

              {/* Typing indicator — only when waiting for the first step */}
              {sending &&
                !messages.some(
                  (m) => m.role === 'assistant' && !m.content && m.reasoning_trace?.length
                ) && (
                  <div className="flex flex-col gap-3 px-4 py-3">
                    <div className="w-8 h-8 rounded-full bg-dark-lime flex items-center justify-center text-white shrink-0">
                      <BotMessageSquare size={14} />
                    </div>
                    <div className="flex items-center gap-1.5 bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
                      <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
                      <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                      <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
                    </div>
                  </div>
                )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
        {/* Input (pinned to bottom) */}
        <ChatInput
          value={input}
          onChange={setInput}
          onSubmit={handleSubmit}
          loading={sending}
          textareaRef={textareaRef}
        />
      </div>
    </div>
  );
}
