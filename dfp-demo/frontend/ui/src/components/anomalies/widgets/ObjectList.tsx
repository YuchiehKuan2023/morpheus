import { formatScalar, getItemTitle, objectEntries, toTitleCase } from '@/utils';
import type { FC } from 'react';

interface Props {
  fieldKey: string;
  items: Record<string, unknown>[];
}

/** Renders an array of plain objects as numbered cards. */
export const ObjectList: FC<Props> = (props) => {
  const { fieldKey, items } = props;

  const title = toTitleCase(fieldKey.replace(/_/g, ' '));
  const EXCLUDED_KEYS = ['anomaly_id', 'user_id', 'auto_actionable', 'priority', 'root_cause'];
  const className =
    fieldKey === 'similar_detections' ? 'grid grid-cols-3 gap-2 similar-detections' : null;

  return (
    <div className="space-y-2">
      <div className="result-row">
        <span className="result-row--title">{title}</span>
      </div>
      <div {...(className ? { className } : {})}>
        {items.map((item, i) => {
          const title = getItemTitle(item);
          const entries = objectEntries(item, true);

          return (
            <div key={i} className="rounded-lg bg-muted/30 space-y-1.5 mt-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="numbered-item">{i + 1}</span>
                  {title && <span className="text-sm font-bold">{title}</span>}
                </div>
                {entries.length > 0 && (
                  <div className="grid grid-cols-1 gap-x-4 gap-y-1 pl-6">
                    {entries.map(([k, v]) => {
                      if (EXCLUDED_KEYS.includes(k)) return null;

                      const key = k === 'ts' ? 'date' : k.replace(/_/g, ' ');

                      return (
                        <div key={k}>
                          <div className="text-sm pl-1">
                            <strong>{toTitleCase(key)}</strong>: {formatScalar(k, v)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
