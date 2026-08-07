import { useState } from 'react';
import { Archive, ArchiveRestore, Download, EllipsisVertical, Pencil, Trash2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui';

interface ConversationMenuProps {
  sessionId: number;
  title: string;
  status: 'active' | 'archived';
  onRename: (id: number, title: string) => void;
  onArchive: (id: number) => void;
  onUnarchive: (id: number) => void;
  onDelete: (id: number) => void;
  onExport: (id: number) => void;
}

export default function ConversationMenu({
  sessionId,
  title,
  status,
  onRename,
  onArchive,
  onUnarchive,
  onDelete,
  onExport,
}: ConversationMenuProps) {
  const [renameOpen, setRenameOpen] = useState(false);
  const [newTitle, setNewTitle] = useState(title);

  function handleRenameSubmit() {
    const trimmed = newTitle.trim();
    if (trimmed && trimmed !== title) {
      onRename(sessionId, trimmed);
    }
    setRenameOpen(false);
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-gray-700 shrink-0 p-0.5 rounded cursor-pointer"
            aria-label="Conversation options"
            onClick={(e) => e.stopPropagation()}
          >
            <EllipsisVertical size={14} />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          side="right"
          className="w-44 glass-card glass-card--xs"
          onClick={(e) => e.stopPropagation()}
        >
          <DropdownMenuItem
            onClick={() => {
              setNewTitle(title);
              setRenameOpen(true);
            }}
          >
            <Pencil size={13} className="mr-2" />
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => onExport(sessionId)}>
            <Download size={13} className="mr-2" />
            Export
          </DropdownMenuItem>
          <div className="separator -ml-2 -mr-2 mt-2 mb-2" />
          {status === 'active' ? (
            <DropdownMenuItem onClick={() => onArchive(sessionId)}>
              <Archive size={13} className="mr-2" />
              Archive
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onClick={() => onUnarchive(sessionId)}>
              <ArchiveRestore size={13} className="mr-2" />
              Restore
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            className="text-red-600 focus:text-red-600"
            onClick={() => onDelete(sessionId)}
          >
            <Trash2 size={13} className="mr-2" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Rename dialog */}
      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent className="sm:max-w-sm" onClick={(e) => e.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>Rename Conversation</DialogTitle>
          </DialogHeader>
          <input
            autoFocus
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleRenameSubmit();
            }}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-gray-300"
          />
          <DialogFooter>
            <button
              onClick={() => setRenameOpen(false)}
              className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={handleRenameSubmit}
              disabled={!newTitle.trim() || newTitle.trim() === title}
              className="px-3 py-1.5 text-sm font-medium text-white bg-dark-lime rounded-lg disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
            >
              Save
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
