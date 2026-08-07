import { cn } from '@/utils';
import type { FC } from 'react';

interface Props {
  height?: number;
  width?: number;
  marginBottom?: number;
}

const Spinner: FC<Props> = ({ height, width, marginBottom }) => {
  return (
    <div
      className={cn(
        'animate-spin rounded-full border-b-2 border-brand-dark-lime',
        height ? `h-${height}` : 'h-12',
        width ? `w-${width}` : 'w-12',
        marginBottom !== undefined ? `mb-${marginBottom}` : 'mb-4'
      )}
    ></div>
  );
};

export default Spinner;
