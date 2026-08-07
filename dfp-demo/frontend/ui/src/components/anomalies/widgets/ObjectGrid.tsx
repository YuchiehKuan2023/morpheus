import { formatScalar, objectEntries } from '@/utils';
import type { FC } from 'react';

interface Props {
  item: Record<string, unknown>;
}

/** Renders a single plain-object as a two-column key-value grid. */
export const ObjectGrid: FC<Props> = (props) => {
  const { item } = props;

  const entries = objectEntries(item, false);

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
      {entries.map(([k, v]) => (
        <div key={k}>
          <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
            {k.replace(/_/g, ' ')}
          </div>
          <div className="text-sm">{formatScalar(k, v)}</div>
        </div>
      ))}
    </div>
  );
};
