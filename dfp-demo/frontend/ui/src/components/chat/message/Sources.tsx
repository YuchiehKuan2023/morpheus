import { Badge } from '@/components';
import { Database } from 'lucide-react';
import type { FC } from 'react';

interface Props {
  sources?: string[];
}

const Sources: FC<Props> = ({ sources }) => {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-1">
      <span className="text-gray-400 font-medium w-18">Sources</span>
      <div className="inline-flex flex-wrap gap-1.5">
        {sources.map((src) => (
          <Badge key={src} className="inline-flex items-center gap-1">
            <Database size={11} />
            {src}
          </Badge>
        ))}
      </div>
    </div>
  );
};

export default Sources;
