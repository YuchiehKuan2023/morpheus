import { useAuth } from '@/contexts/useAuth';
import { api } from '@/services/api';
import { Bell } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { FC } from 'react';
import type { AnalystNotification } from '@/types';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { AnomalyDetailDialog } from '@/components/anomalies/AnomalyDetailDialog';
import { cn } from '@/utils';

const POLL_INTERVAL = 30_000; // 30 seconds

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

const Notifications: FC = () => {
  const { user } = useAuth();

  const [notifications, setNotifications] = useState<AnalystNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [dialogAnomalyId, setDialogAnomalyId] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchUnreadCount = useCallback(async () => {
    try {
      const count = await api.getUnreadCount();
      setUnreadCount(count);
    } catch {
      // silent
    }
  }, []);

  const fetchNotifications = useCallback(async () => {
    try {
      const data = await api.getNotifications(20);
      setNotifications(data);
      setUnreadCount(data.filter((n) => !n.seenAt).length);
    } catch {
      // silent
    }
  }, []);

  // Poll for unread count
  useEffect(() => {
    if (!user) return;
    const id = setInterval(fetchUnreadCount, POLL_INTERVAL);
    intervalRef.current = id;
    return () => clearInterval(id);
  }, [user, fetchUnreadCount]);

  // Initial fetch on mount
  useEffect(() => {
    if (user) {
      void fetchUnreadCount();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const handleOpenChange = (isOpen: boolean) => {
    setOpen(isOpen);
    if (isOpen) void fetchNotifications();
  };

  const handleMarkAllRead = async () => {
    await api.markAllNotificationsSeen();
    setNotifications((prev) =>
      prev.map((n) => ({ ...n, seenAt: n.seenAt ?? new Date().toISOString() }))
    );
    setUnreadCount(0);
  };

  const handleMarkRead = async (id: number) => {
    await api.markNotificationSeen(id);
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, seenAt: new Date().toISOString() } : n))
    );
    setUnreadCount((c) => Math.max(0, c - 1));
  };

  if (!user) return null;

  return (
    <>
      <DropdownMenu open={open} onOpenChange={handleOpenChange}>
        <DropdownMenuTrigger asChild>
          <span className="top-navigation__item top-navigation__notifications cursor-pointer bg-gray-100! rounded-full! w-12 h-12 gap-0! p-0! -mr-3 flex items-center justify-center relative">
            <Bell width={16} height={16} />
            {unreadCount > 0 && (
              <span className="absolute -top-0.5 -right-0.5 bg-dark-lime text-white text-[10px] font-bold rounded-full min-w-4.5 h-4.5 flex items-center justify-center px-1">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </span>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="w-80 bg-white shadow-lg border border-gray-200 glass-card glass-card--xs rounded-md! pb-1!"
        >
          <DropdownMenuLabel className="flex items-center justify-between">
            <span className="-ml-2">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={(e) => {
                  e.preventDefault();
                  handleMarkAllRead();
                }}
                className="text-xs text-brand-lime hover:underline flex items-center gap-1 font-normal"
              >
                Mark all read
              </button>
            )}
          </DropdownMenuLabel>
          <div className="separator -ml-2 -mr-2 mt-1.5" />
          {notifications.length === 0 && (
            <div className="px-2 py-6 text-center text-sm text-muted-foreground">
              No notifications
            </div>
          )}
          {notifications.map((n) => (
            <DropdownMenuItem
              key={n.id}
              className={cn(
                'flex flex-col items-start gap-1 p-2 border-t border-white -ml-2 -mr-2 rounded-none',
                !n.seenAt && 'bg-pale-lime'
              )}
              onClick={() => {
                if (!n.seenAt) handleMarkRead(n.id);
                if (n.type === 'anomaly_assigned' && n.anomalyId) {
                  setDialogAnomalyId(n.anomalyId);
                  setOpen(false);
                }
              }}
            >
              <div className="flex items-start gap-2 w-full">
                <div className={`flex-1 min-w-0`}>
                  <p className="text-sm font-medium truncate pb-1">{n.title}</p>
                  {n.message && (
                    <p className="text-xs text-muted-foreground line-clamp-2">{n.message}</p>
                  )}
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {n.createdAt ? timeAgo(n.createdAt) : ''}
                  </p>
                </div>
              </div>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <AnomalyDetailDialog
        anomalyId={dialogAnomalyId}
        open={dialogAnomalyId !== null}
        onClose={() => setDialogAnomalyId(null)}
      />
    </>
  );
};

export default Notifications;
