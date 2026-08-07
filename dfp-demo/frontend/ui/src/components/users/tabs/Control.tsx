import { cn } from '@/utils';
import type { FC, ReactNode } from 'react';

interface Props {
  label: string;
  control: ReactNode;
  actions?: ReactNode;
  options?: {
    hideLabel?: boolean;
  };
}

const Control: FC<Props> = (props) => {
  const { label, control, actions, options } = props;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center">
        <span
          className={cn(
            'text-muted-foreground font-medium pl-1',
            options?.hideLabel && 'invisible'
          )}
        >
          {label}:
        </span>
        {actions && <div className="flex items-center gap-1">{actions}</div>}
      </div>
      <div className="flex items-center">{control}</div>
    </div>
  );
};

export default Control;
