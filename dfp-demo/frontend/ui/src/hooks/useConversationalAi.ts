import { chatApi } from '@/services/chat';
import type { ChatMessage, ChatSession, TraceStep } from '@/types/chat';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

function useConversationalAi() {
  const { conversationId } = useParams<{ conversationId?: string }>();

  const navigate = useNavigate();

  // Sessions
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [archivedSessions, setArchivedSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [loadingSessions, setLoadingSessions] = useState(false);

  // Messages
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);

  // Input / query state
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  // Suggestions
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const activeSessionIdRef = useRef(activeSessionId);

  activeSessionIdRef.current = activeSessionId;

  // ----------------------------------------------------------------
  // Bootstrap
  // ----------------------------------------------------------------
  useEffect(() => {
    loadSessions();
    loadArchivedSessions();
    chatApi
      .getSuggestions()
      .then((r) => setSuggestions(r.suggestions))
      .catch(() => {});
  }, []);

  // Sync URL param → active session on mount / URL change
  useEffect(() => {
    const urlId = conversationId ? parseInt(conversationId, 10) : null;
    if (urlId && !isNaN(urlId) && urlId !== activeSessionIdRef.current) {
      handleSelectSession(urlId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  // Scroll to bottom on new messages (instant, no smooth animation)
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
  }, [messages, sending]);

  // ----------------------------------------------------------------
  // Session helpers
  // ----------------------------------------------------------------
  async function loadSessions() {
    setLoadingSessions(true);
    try {
      const data = await chatApi.listSessions('active');
      setSessions(data);
    } catch {
      // non-fatal
    } finally {
      setLoadingSessions(false);
    }
  }

  async function loadArchivedSessions() {
    try {
      const data = await chatApi.listSessions('archived');
      setArchivedSessions(data);
    } catch {
      // non-fatal
    }
  }

  async function handleNewSession() {
    try {
      const session = await chatApi.createSession();
      setSessions((prev) => [session, ...prev]);
      setActiveSessionId(session.id);
      navigate(`/chat/${session.id}`, { replace: true });
      setMessages([]);
      setError(null);
    } catch {
      setError('Failed to create a new conversation.');
    }
  }

  async function handleSelectSession(id: number) {
    if (id === activeSessionId) return;
    setActiveSessionId(id);
    navigate(`/chat/${id}`, { replace: true });
    setMessages([]);
    setError(null);
    setLoadingMessages(true);
    try {
      const detail = await chatApi.getSession(id);
      setMessages(detail.messages);
    } catch {
      setError('Failed to load conversation.');
    } finally {
      setLoadingMessages(false);
    }
  }

  /** Silently reload active conversation messages from the server. */
  async function reloadActiveConversation(sessionId: number) {
    try {
      const detail = await chatApi.getSession(sessionId);
      setMessages(detail.messages);
    } catch {
      // non-fatal — keep existing messages
    }
  }

  async function handleDeleteSession(id: number) {
    try {
      await chatApi.deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      setArchivedSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(null);
        setMessages([]);
        navigate('/chat', { replace: true });
      }
    } catch {
      setError('Failed to delete conversation.');
    }
  }

  async function handleArchiveSession(id: number) {
    try {
      await chatApi.archiveSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(null);
        setMessages([]);
        navigate('/chat', { replace: true });
      }
      loadArchivedSessions();
    } catch {
      setError('Failed to archive conversation.');
    }
  }

  async function handleUnarchiveSession(id: number) {
    try {
      await chatApi.unarchiveSession(id);
      setArchivedSessions((prev) => prev.filter((s) => s.id !== id));
      loadSessions();
    } catch {
      setError('Failed to restore conversation.');
    }
  }

  async function handleRenameSession(id: number, title: string) {
    try {
      await chatApi.renameSession(id, title);
      const updater = (prev: ChatSession[]) => prev.map((s) => (s.id === id ? { ...s, title } : s));
      setSessions(updater);
      setArchivedSessions(updater);
    } catch {
      setError('Failed to rename conversation.');
    }
  }

  async function handleExportSession(id: number) {
    try {
      const data = await chatApi.exportSession(id);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${data.title.replace(/[^a-zA-Z0-9]/g, '_')}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError('Failed to export conversation.');
    }
  }

  // ----------------------------------------------------------------
  // Query
  // ----------------------------------------------------------------
  async function handleSubmit() {
    const queryText = input.trim();
    if (!queryText || sending) return;
    setError(null);

    // Ensure we have a session
    let sessionId = activeSessionId;
    if (!sessionId) {
      try {
        const session = await chatApi.createSession();
        setSessions((prev) => [session, ...prev]);
        setActiveSessionId(session.id);
        navigate(`/chat/${session.id}`, { replace: true });
        sessionId = session.id;
      } catch {
        setError('Failed to start a conversation. Please try again.');
        return;
      }
    }

    // Optimistically add user message to UI
    const now = new Date().toISOString();
    const optimisticUser: ChatMessage = {
      id: Date.now(),
      session_id: sessionId,
      role: 'user',
      content: queryText,
      created_at: now,
    };
    setMessages((prev) => [...prev, optimisticUser]);
    setInput('');
    setSending(true);

    // Create a placeholder assistant message that will be updated as steps stream in
    const assistantId = Date.now() + 1;
    const placeholderMsg: ChatMessage = {
      id: assistantId,
      session_id: sessionId,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      reasoning_trace: [],
    };
    setMessages((prev) => [...prev, placeholderMsg]);

    const updateAssistant = (updater: (msg: ChatMessage) => ChatMessage) => {
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? updater(m) : m)));
    };

    try {
      const controller = chatApi.queryStream(
        sessionId,
        queryText,
        // onStep — append to the placeholder message's trace
        (step: TraceStep) => {
          updateAssistant((msg) => ({
            ...msg,
            reasoning_trace: [...(msg.reasoning_trace ?? []), step],
          }));
        },
        // onAnswer — fill in the final content + metadata, then silently
        // reload the full conversation from the server so DB IDs and
        // stored reasoning traces are accurate.
        (result) => {
          updateAssistant((msg) => ({
            ...msg,
            content: result.answer,
            tools_used: result.tools_used,
            intent: result.intent,
            confidence: result.confidence,
            sources: result.sources,
            suggested_followups: result.suggested_followups,
          }));
          setSending(false);
          loadSessions();
          loadArchivedSessions();
          // Silently reload the conversation to sync DB state
          reloadActiveConversation(sessionId!);
        },
        // onError
        (errMsg: string) => {
          setError(errMsg);
          // Remove the empty placeholder on error
          setMessages((prev) => prev.filter((m) => m.id !== assistantId));
          setSending(false);
        }
      );
      streamAbortRef.current = controller;
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to get a response. Please try again.';
      setError(msg);
      setMessages((prev) => prev.filter((m) => m.id !== assistantId));
      setSending(false);
    }
  }

  function handleSuggestionSelect(q: string) {
    setInput(q);
  }

  // Add / remove body class for layout escape (like Graph page)
  useEffect(() => {
    document.body.classList.add('page-chat');
    return () => document.body.classList.remove('page-chat');
  }, []);

  // ----------------------------------------------------------------
  // Render
  // ----------------------------------------------------------------
  const showEmpty = !loadingMessages && messages.length === 0 && !sending;

  return {
    data: {
      showEmpty,
      messagesEndRef,
      textareaRef,
    },
    state: {
      sessions,
      archivedSessions,
      activeSessionId,
      loadingSessions,
      messages,
      loadingMessages,
      input,
      sending,
      error,
      suggestions,
      setInput,
    },
    handlers: {
      handleNewSession,
      handleSelectSession,
      handleDeleteSession,
      handleArchiveSession,
      handleUnarchiveSession,
      handleRenameSession,
      handleExportSession,
      handleSubmit,
      handleSuggestionSelect,
    },
  };
}

export default useConversationalAi;
