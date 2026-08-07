import { Badge } from '@/components';
import { TOOL_LABELS } from '@/constants/chat';
import type { FC } from 'react';

interface Props {
  toolsUsed?: string[];
  isUser: boolean;
}

const Tools: FC<Props> = ({ toolsUsed, isUser }) => {
  if (isUser || !toolsUsed || toolsUsed.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-1">
      <span className="text-gray-400 font-medium w-18 shrink-0">Tools</span>
      <div className="inline-flex flex-wrap gap-1.5">
        {toolsUsed!.map((tool) => (
          <Badge key={tool} variant="lime" className="inline-flex items-center gap-1">
            {TOOL_LABELS[tool] ?? tool}
          </Badge>
        ))}
      </div>
    </div>
  );
};

export default Tools;
