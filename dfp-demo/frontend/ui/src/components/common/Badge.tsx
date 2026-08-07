import { cn } from '@/utils';
import type { FC, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  variant?: 'default' | 'light' | 'lime';
  className?: string;
}

const Badge: FC<Props> = (props) => {
  const { children, variant, className } = props;

  const badgeClass = cn('dfp-badge', variant, className);

  return <span className={badgeClass}>{children}</span>;
};

export default Badge;
