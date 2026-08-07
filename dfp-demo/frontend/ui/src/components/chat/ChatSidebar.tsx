import { useState } from 'react';
import { Plus, Loader2 } from 'lucide-react';
import { cn } from '@/utils';
import { formatDistanceToNow } from 'date-fns';
import type { ChatSession } from '@/types';
import ConversationMenu from './ConversationMenu';
import { PillTabs } from '@/components';
import { TabsContent } from '@/components/ui';

interface ChatSidebarProps {
  sessions: ChatSession[];
  archivedSessions: ChatSession[];
  activeSessionId: number | null;
  onSelectSession: (id: number) => void;
  onNewSession: () => void;
  onDeleteSession: (id: number) => void;
  onArchiveSession: (id: number) => void;
  onUnarchiveSession: (id: number) => void;
  onRenameSession: (id: number, title: string) => void;
  onExportSession: (id: number) => void;
  loadingSessions: boolean;
}

const TABS = [
  { id: 'active', label: 'Current' },
  { id: 'archived', label: 'Archived' },
];

function formatDate(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return '';
  }
}

function SessionList({
  sessions,
  activeSessionId,
  onSelectSession,
  onDeleteSession,
  onArchiveSession,
  onUnarchiveSession,
  onRenameSession,
  onExportSession,
  loading,
  emptyText,
}: {
  sessions: ChatSession[];
  activeSessionId: number | null;
  onSelectSession: (id: number) => void;
  onDeleteSession: (id: number) => void;
  onArchiveSession: (id: number) => void;
  onUnarchiveSession: (id: number) => void;
  onRenameSession: (id: number, title: string) => void;
  onExportSession: (id: number) => void;
  loading: boolean;
  emptyText: string;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-gray-400">
        <Loader2 size={18} className="animate-spin" />
      </div>
    );
  }

  if (sessions.length === 0) {
    return <p className="text-center text-xs text-gray-400 py-8">{emptyText}</p>;
  }

  return (
    <>
      {sessions.map((s) => {
        return (
          <div
            key={s.id}
            className={cn(
              'group flex items-start gap-2 px-3 py-2.5 cursor-pointer transition-colors ml-1 border-b border-white',
              activeSessionId === s.id
                ? 'bg-pale-lime text-black'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
            )}
            onClick={() => onSelectSession(s.id)}
          >
            <div className="flex-1 min-w-0">
              <span className="text-xs font-medium truncate block leading-tight">{s.title}</span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[10px] text-gray-400">{s.message_count ?? 0} messages</span>
                <span className="text-[10px] text-gray-400">·</span>
                <span className="text-[10px] text-gray-400 truncate">
                  {formatDate(s.updated_at)}
                </span>
              </div>
            </div>
            <ConversationMenu
              sessionId={s.id}
              title={s.title}
              status={s.status}
              onRename={onRenameSession}
              onArchive={onArchiveSession}
              onUnarchive={onUnarchiveSession}
              onDelete={onDeleteSession}
              onExport={onExportSession}
            />
          </div>
        );
      })}
    </>
  );
}

export default function ChatSidebar({
  sessions,
  archivedSessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  onArchiveSession,
  onUnarchiveSession,
  onRenameSession,
  onExportSession,
  loadingSessions,
}: ChatSidebarProps) {
  const [tab, setTab] = useState('active');

  return (
    <aside className="flex flex-col w-72 shrink-0 border-r border-gray-200 mt-0.75">
      {/* Tabs */}
      <PillTabs
        tabs={TABS}
        value={tab}
        onValueChange={setTab}
        compact
        navClassName="px-3 pt-3"
        action={{
          content: <Plus size={14} />,
          onClick: onNewSession,
          position: 'right',
        }}
      >
        <TabsContent value="active" className="flex-1 overflow-y-auto py-2">
          <div className="separator ml-1 mb-3" />
          <SessionList
            sessions={sessions}
            activeSessionId={activeSessionId}
            onSelectSession={onSelectSession}
            onDeleteSession={onDeleteSession}
            onArchiveSession={onArchiveSession}
            onUnarchiveSession={onUnarchiveSession}
            onRenameSession={onRenameSession}
            onExportSession={onExportSession}
            loading={loadingSessions}
            emptyText="No conversations yet"
          />
        </TabsContent>
        <TabsContent value="archived" className="flex-1 overflow-y-auto py-2">
          <div className="separator ml-1" />
          <SessionList
            sessions={archivedSessions}
            activeSessionId={activeSessionId}
            onSelectSession={onSelectSession}
            onDeleteSession={onDeleteSession}
            onArchiveSession={onArchiveSession}
            onUnarchiveSession={onUnarchiveSession}
            onRenameSession={onRenameSession}
            onExportSession={onExportSession}
            loading={loadingSessions}
            emptyText="No archived conversations"
          />
        </TabsContent>
      </PillTabs>
    </aside>
  );
}
