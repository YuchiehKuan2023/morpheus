import type {
  AgentMetrics,
  ChatSession,
  ChatSessionDetail,
  ChatSessionExport,
  QueryResponse,
  SuggestionsResponse,
  TraceStep,
} from '@/types';
import { API_BASE_URL } from '@/constants/shared';

const getBase = () => `${API_BASE_URL}/api/v1/chat`;

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

export const chatApi = {
  createSession: (title = 'New Conversation') =>
    fetchJson<ChatSession>(`${getBase()}/sessions`, {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),

  listSessions: (status: 'active' | 'archived' = 'active') =>
    fetchJson<ChatSession[]>(`${getBase()}/sessions?status=${status}`),

  getSession: (id: number) => fetchJson<ChatSessionDetail>(`${getBase()}/sessions/${id}`),

  deleteSession: (id: number) =>
    fetchJson<{ deleted: boolean; session_id: number }>(`${getBase()}/sessions/${id}`, {
      method: 'DELETE',
    }),

  archiveSession: (id: number) =>
    fetchJson<{ archived: boolean; session_id: number }>(`${getBase()}/sessions/${id}/archive`, {
      method: 'POST',
    }),

  unarchiveSession: (id: number) =>
    fetchJson<{ unarchived: boolean; session_id: number }>(
      `${getBase()}/sessions/${id}/unarchive`,
      { method: 'POST' }
    ),

  renameSession: (id: number, title: string) =>
    fetchJson<{ renamed: boolean; session_id: number; title: string }>(
      `${getBase()}/sessions/${id}/rename`,
      { method: 'PATCH', body: JSON.stringify({ title }) }
    ),

  exportSession: (id: number) => fetchJson<ChatSessionExport>(`${getBase()}/sessions/${id}/export`),

  query: (session_id: number, query: string) =>
    fetchJson<QueryResponse>(`${getBase()}/query`, {
      method: 'POST',
      body: JSON.stringify({ session_id, query }),
    }),

  getSuggestions: () => fetchJson<SuggestionsResponse>(`${getBase()}/suggestions`),

  getAgentMetrics: () => fetchJson<AgentMetrics>(`${getBase()}/agent-metrics`),

  queryStream: (
    sessionId: number,
    query: string,
    onStep: (step: TraceStep) => void,
    onAnswer: (response: QueryResponse) => void,
    onError: (error: string) => void
  ): AbortController => {
    const controller = new AbortController();

    fetch(`${getBase()}/query/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, query }),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`API ${res.status}`);
        const reader = res.body?.getReader();
        if (!reader) throw new Error('No response body');

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';

          let eventType = '';
          let eventData = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              eventData = line.slice(6);
            } else if (line === '' && eventType && eventData) {
              const parsed = JSON.parse(eventData);
              if (eventType === 'step') onStep(parsed as TraceStep);
              else if (eventType === 'answer') onAnswer(parsed as QueryResponse);
              else if (eventType === 'error') onError(parsed.detail ?? 'Unknown error');
              eventType = '';
              eventData = '';
            }
          }
        }
      })
      .catch((err) => {
        if (err.name !== 'AbortError') onError(err.message);
      });

    return controller;
  },
};
