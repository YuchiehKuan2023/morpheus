import { GlassCard } from '@/components';
import type { FC, ReactNode } from 'react';

interface Props {
  title: ReactNode;
  description: ReactNode;
  actions?: ReactNode;
  separator?: boolean;
}

export const DialogSection: FC<Props> = ({ title, description, actions, separator }) => {
  return (
    <GlassCard
      className="no-border no-shadow glass-card--xs"
      title={
        <div className="flex flex-col">
          <div className="block text-[21px]">{title}</div>
        </div>
      }
      description={
        <div className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">
          {description}
        </div>
      }
      {...(actions
        ? { actions: <div className="flex flex-wrap items-center gap-2">{actions}</div> }
        : {})}
      {...(separator ? { separator: true } : {})}
    />
  );
};
