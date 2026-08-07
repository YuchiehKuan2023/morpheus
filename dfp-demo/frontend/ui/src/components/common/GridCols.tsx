import { COLS_CLASS } from '@/constants';
import { cn } from '@/utils';
import type { FC, ReactNode } from 'react';

interface Props {
  cols: number;
  className?: string;
  children: ReactNode;
}

const GridCols: FC<Props> = ({ cols, className, children }) => {
  const classNames = cn('grid gap-4', COLS_CLASS[cols], className);
  return <div className={classNames}>{children}</div>;
};

export default GridCols;
