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
}

const LoadingDialog: FC<Props> = (props) => {
  const { open, onClose, title } = props;

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="sr-only">Loading user details</DialogDescription>
        </DialogHeader>
        <div className="py-10 text-sm text-muted-foreground">Loading…</div>
      </DialogContent>
    </Dialog>
  );
};

export default LoadingDialog;
