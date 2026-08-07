import type { FC } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui';

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  error: string | null;
}

const ErrorDialog: FC<Props> = (props) => {
  const { open, onClose, title, error } = props;

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="sr-only">Loading user details failed</DialogDescription>
        </DialogHeader>
        <div className="py-10 space-y-4">
          <p className="text-sm text-muted-foreground">{error ?? 'Unable to load user details.'}</p>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default ErrorDialog;
