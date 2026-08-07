import { Badge } from '@/components';
import { formatDateTime } from '@/utils';
import type { FC } from 'react';

export interface AttackChainItem {
  ts: string;
  event_type: string;
  significance: string;
}

interface Props {
  items: AttackChainItem[];
}

const ITEM_W = 80;
const GAP = 8;

const SCROLL_THRESHOLD = 8;

export const AttackChainTimeline: FC<Props> = ({ items }) => {
  if (!items || items.length === 0) return null;

  const scrollable = items.length >= SCROLL_THRESHOLD;
  const totalWidth = items.length * (ITEM_W + GAP) + 48;

  return (
    <div className="space-y-2">
      <div className="separator -ml-3 -mr-3 mt-4 mb-4" />
      <div className="result-row">
        <span className="result-row--title">Attack Chain</span>
        <span className="text-xs text-muted-foreground ml-2">({items.length} events)</span>
      </div>

      <div
        style={{
          overflowX: scrollable ? 'auto' : 'visible',
          paddingBottom: '1.5rem',
          paddingTop: '1rem',
        }}
      >
        <div
          style={{
            position: 'relative',
            ...(scrollable ? { minWidth: `calc(${totalWidth}px + 30px)` } : {}),
            paddingTop: '7rem',
            paddingBottom: '7rem',
          }}
        >
          {/* Main horizontal timeline line */}
          <div
            style={{
              position: 'absolute',
              top: '50%',
              left: 0,
              right: 0,
              height: '3px',
              transform: 'translateY(-50%)',
              backgroundColor: 'var(--brand-dark-lime)',
            }}
          >
            {/* Arrow at the end */}
            <div
              style={{
                position: 'absolute',
                right: '-8px',
                top: '50%',
                transform: 'translateY(-50%)',
                width: 0,
                height: 0,
                borderTop: '8px solid transparent',
                borderBottom: '8px solid transparent',
                borderLeft: '12px solid var(--brand-dark-lime)',
              }}
            />
          </div>

          {/* Timeline events */}
          <div
            style={{
              position: 'relative',
              display: 'flex',
              justifyContent: scrollable ? 'flex-start' : 'center',
              alignItems: 'center',
              gap: `${GAP}px`,
              padding: scrollable ? '0 0 0 30px' : '0 16px',
            }}
          >
            {items.map((item, idx) => {
              const isAbove = idx % 2 === 0;

              return (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    position: 'relative',
                    width: `${ITEM_W}px`,
                    flexShrink: 0,
                  }}
                >
                  {/* Content above the timeline */}
                  {isAbove && (
                    <div
                      style={{
                        position: 'absolute',
                        bottom: '100%',
                        marginBottom: '1.75rem',
                        width: '190px',
                        textAlign: 'center',
                      }}
                    >
                      <div
                        style={{
                          fontSize: '11px',
                          fontWeight: 600,
                          color: 'var(--brand-dark-lime)',
                          marginBottom: '3px',
                        }}
                      >
                        {formatDateTime(item.ts)}
                      </div>
                      <Badge className="inline-block">
                        {item.event_type.replace(
                          'Unauthorized Application Access',
                          'Unauthorized App'
                        )}
                      </Badge>
                      <p
                        style={{
                          fontSize: '10px',
                          color: 'var(--muted-foreground)',
                          margin: '6px 0 6px 0',
                          lineHeight: 1.3,
                        }}
                      >
                        {item.significance || '(No additional details)'}
                      </p>
                      {/* Dashed vertical connector down to the line */}
                      <div
                        style={{
                          position: 'absolute',
                          left: '50%',
                          transform: 'translateX(-50%)',
                          top: '100%',
                          width: '2px',
                          height: '1.75rem',
                          borderLeft: '2px dashed var(--brand-dark-lime)',
                        }}
                      />
                    </div>
                  )}

                  {/* Circle marker on the timeline */}
                  <div
                    style={{
                      position: 'relative',
                      zIndex: 10,
                      width: '30px',
                      height: '30px',
                      borderRadius: '50%',
                      backgroundColor: '#ffffff',
                      border: '3px solid var(--brand-dark-lime)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <span
                      style={{
                        fontSize: '10px',
                        fontWeight: 700,
                        color: 'var(--brand-dark-lime)',
                      }}
                    >
                      {idx + 1}
                    </span>
                  </div>

                  {/* Content below the timeline */}
                  {!isAbove && (
                    <div
                      style={{
                        position: 'absolute',
                        top: '100%',
                        marginTop: '1.75rem',
                        width: '190px',
                        textAlign: 'center',
                      }}
                    >
                      {/* Dashed vertical connector up to the line */}
                      <div
                        style={{
                          position: 'absolute',
                          left: '50%',
                          transform: 'translateX(-50%)',
                          bottom: '100%',
                          width: '2px',
                          height: '1.75rem',
                          borderLeft: '2px dashed var(--brand-dark-lime)',
                        }}
                      />
                      <Badge className="mt-1.5 inline-block">
                        {item.event_type.replace(
                          'Unauthorized Application Access',
                          'Unauthorized App'
                        )}
                      </Badge>
                      <p
                        style={{
                          fontSize: '10px',
                          color: 'var(--muted-foreground)',
                          margin: '8px 0 0',
                          lineHeight: 1.3,
                        }}
                      >
                        {item.significance || '(No additional details)'}
                      </p>
                      <div
                        style={{
                          fontSize: '11px',
                          fontWeight: 600,
                          color: 'var(--brand-dark-lime)',
                          marginTop: '3px',
                        }}
                      >
                        {formatDateTime(item.ts)}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="separator -ml-3 -mr-3 mt-4 mb-4" />
    </div>
  );
};
