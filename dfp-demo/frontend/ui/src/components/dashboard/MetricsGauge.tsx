import { GAUGE_CX, GAUGE_CY, GAUGE_PATH, SEMI_CIRC } from '@/constants';
import type { GaugeDef } from '@/types';
import type { FC } from 'react';

interface Props {
  def: GaugeDef;
  value: number;
}

const MetricsGauge: FC<Props> = (props) => {
  const { def, value } = props;

  const clamped = Math.min(value, def.max);
  const dashLen = (clamped / def.max) * SEMI_CIRC;
  const display = def.format ? def.format(value) : value.toFixed(1);

  return (
    <div className="glass-card glass-card--xs flex items-center flex-col gap-3">
      <svg viewBox="0 0 72 38" width="72" height="38" aria-label={`${def.label}: ${display}`}>
        {/* track */}
        <path
          d={GAUGE_PATH}
          fill="none"
          stroke="rgba(0,0,0,0.03)"
          strokeWidth="7"
          strokeLinecap="round"
        />
        {/* fill */}
        <path
          d={GAUGE_PATH}
          fill="none"
          stroke={def.color}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${dashLen} ${SEMI_CIRC}`}
        />
        {/* value */}
        <text
          x={GAUGE_CX}
          y={GAUGE_CY - 3}
          textAnchor="middle"
          fontSize="11"
          fill="var(--brand-black)"
          fontWeight="600"
          fontFamily="monospace"
        >
          {display}
        </text>
      </svg>
      <span className="text-xs text-center leading-tight font-bold">{def.label}</span>
    </div>
  );
};

export default MetricsGauge;
