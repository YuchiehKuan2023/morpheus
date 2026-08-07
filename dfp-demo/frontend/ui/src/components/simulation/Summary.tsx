import type { FC } from 'react';
import { GridCols } from '@/components';
import type { SummaryData } from './summaryMappers';
import { cn } from '@/utils';

interface Props {
  data: SummaryData;
}

const Summary: FC<Props> = (props) => {
  const { data } = props;
  const { anomalyScore, investigationStatus, riskScore, rootCause, severity } = data;

  return (
    <GridCols cols={1}>
      <div className="sim-event-card__anomaly-summary">
        <div className="sim-event-card__summary-rows">
          {rootCause && (
            <div className="sim-event-card__summary-row">
              <span className="sim-event-card__summary-label">Root cause</span>
              <span className="sim-event-card__summary-value">{rootCause.replace(/_/g, ' ')}</span>
            </div>
          )}
          {severity && (
            <div className="sim-event-card__summary-row">
              <span className="sim-event-card__summary-label">Severity</span>
              <span
                className={cn(
                  'sim-event-card__summary-value sim-event-card__summary-severity',
                  `sim-event-card__summary-severity--${severity.toLowerCase()}`
                )}
              >
                {severity}
              </span>
            </div>
          )}
          {anomalyScore !== null && (
            <div className="sim-event-card__summary-row">
              <span className="sim-event-card__summary-label">Anomaly score</span>
              <span className="sim-event-card__summary-value">{anomalyScore.toFixed(2)}</span>
            </div>
          )}
          {riskScore !== null && (
            <div className="sim-event-card__summary-row">
              <span className="sim-event-card__summary-label">Risk score</span>
              <span className="sim-event-card__summary-value">{riskScore.toFixed(2)}</span>
            </div>
          )}
          {investigationStatus && (
            <div className="sim-event-card__summary-row">
              <span className="sim-event-card__summary-label">Investigation</span>
              <span className="sim-event-card__summary-value">{investigationStatus}</span>
            </div>
          )}
        </div>
      </div>
    </GridCols>
  );
};

export default Summary;
