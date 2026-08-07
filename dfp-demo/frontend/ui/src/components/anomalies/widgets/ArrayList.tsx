import type { FC } from 'react';

interface Props {
  value: unknown[];
  k: string;
}

function splitFlag(flag: string): [string, string] {
  const parts = flag.split(/\|\|| — | - /, 2);
  return [parts[0].trim(), (parts[1] ?? '').trim()];
}

export const ArrayList: FC<Props> = ({ value, k }) => {
  const isFlags = k === 'compliance flags' || k === 'security flags';

  return (
    <div>
      {isFlags && <div className="separator -ml-3 -mr-3 mb-3 mt-4" />}
      <div className="agent-array-list">
        <div className="result-row mb-2">
          <span className="result-row--title">{k}</span>
        </div>
        <div className="flex flex-col gap-1.5 mt-4">
          {value.map((item, i) => {
            const v =
              isFlags && typeof item === 'string'
                ? splitFlag(item)
                : typeof item === 'string'
                  ? item
                  : JSON.stringify(item);
            const displayValue = Array.isArray(v) ? (
              <span>
                <strong>{v[0]}</strong>
                {v[1] ? <> — {v[1]}</> : null}
              </span>
            ) : (
              v
            );
            return (
              <div className="flex items-start gap-2" key={i}>
                <span className="numbered-item shrink-0">{i + 1}</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-muted/60 text-muted-foreground">
                  {displayValue}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      {isFlags && <div className="separator -ml-3 -mr-3 mb-3 mt-4" />}
    </div>
  );
};
