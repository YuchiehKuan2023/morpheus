import { Badge } from '@/components';
import type { FC } from 'react';

interface Props {
  intent?: string;
}

const Intent: FC<Props> = ({ intent }) => {
  if (!intent) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      <span className="text-gray-400 font-medium w-18">Intent</span>
      <Badge className="flex items-center gap-2">
        <span>{intent}</span>
      </Badge>
    </div>
  );
};

export default Intent;
