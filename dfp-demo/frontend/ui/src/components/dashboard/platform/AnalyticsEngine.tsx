import { type FC, type ReactElement } from 'react';
import { ChartCard } from '..';
import { KPICard } from '@/components';
import { aiOrchestrationCapabilities, type Capability } from '.';

interface Props {
  rootCausesCount: number;
  domainsCount: number;
  renderListing: (capability: Capability, sectionKey: string) => ReactElement;
  renderModels: (capabilities: Capability[], sectionKey: string) => ReactElement | null;
}

const AnalyticsEngine: FC<Props> = ({
  rootCausesCount,
  domainsCount,
  renderListing,
  renderModels,
}) => {
  return (
    <ChartCard
      title="AI Intelligence Layer"
      description="AI Orchestrator · auto-labeling · explainability"
      className="no-border no-shadow capability-card capability-card--with-models"
    >
      <>
        <div className="capability-card__main-content">
          <div className="grid grid-cols-2 gap-2 pb-7 pt-3">
            <KPICard title="Root Causes" value={rootCausesCount} size="xs" variant="dark" />
            <KPICard
              title="Domains"
              value={domainsCount}
              size="xs"
              className="no-border no-shadow"
            />
          </div>

          <div className="platform-capabilities-list">
            {aiOrchestrationCapabilities.map((cap) => renderListing(cap, 'analytics'))}
          </div>
        </div>

        {renderModels(aiOrchestrationCapabilities, 'analytics')}
      </>
    </ChartCard>
  );
};

export default AnalyticsEngine;
