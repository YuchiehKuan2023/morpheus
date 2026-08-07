import type { FC } from 'react';
import { Info } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui';

interface InfoTooltipProps {
  content: string;
}

const InfoTooltip: FC<InfoTooltipProps> = ({ content }) => (
  <Tooltip>
    <TooltipTrigger asChild>
      <button
        type="button"
        className="inline-flex items-center text-muted-foreground hover:text-foreground transition-colors"
        aria-label="More information"
      >
        <Info size={14} />
      </button>
    </TooltipTrigger>
    <TooltipContent side="top" className="max-w-sm leading-relaxed">
      {content}
    </TooltipContent>
  </Tooltip>
);

export default InfoTooltip;
