import { type FC, type ReactElement } from 'react';
import { ChartCard } from '..';
import { Badge, KPICard } from '@/components';
import { aiOrchestrationCapabilities, type Capability } from '.';
import type { PlatformStats } from '@/types/dashboard';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  platformStats?: PlatformStats | null;
  renderListing: (capability: Capability, sectionKey: string) => ReactElement;
  renderModels: (capabilities: Capability[], sectionKey: string) => ReactElement | null;
}

const AIOrchestration: FC<Props> = ({ platformStats, renderListing, renderModels }) => {
  const { title, description } = DESC.platformArchitecture.components.aiIntelligenceLayer;

  return (
    <ChartCard
      title={title}
      description={
        <>
          <p className="text-xs text-muted-foreground mb-4 h-12">{description}</p>
          <div className="flex gap-2">
            <Badge>AI Orchestrator</Badge>
            <Badge variant="lime">labeling</Badge>
            <Badge variant="lime">scoring</Badge>
            <Badge variant="lime">explainability</Badge>
          </div>
        </>
      }
      className="no-border no-shadow capability-card capability-card--with-models glass-card--xs"
    >
      <>
        <div className="capability-card__main-content">
          <div className="grid grid-cols-2 gap-2 pb-7 pt-3">
            <KPICard
              title="True Positives"
              value={platformStats != null ? platformStats.truePositives.toLocaleString() : '—'}
              size="xs"
              variant="dark"
            />
            <KPICard
              title="Labeled Records"
              value={platformStats != null ? platformStats.labeledRecords.toLocaleString() : '—'}
              size="xs"
              className="no-border no-shadow"
            />
          </div>

          <div className="platform-capabilities-list">
            <div>
              {aiOrchestrationCapabilities.map((cap) => renderListing(cap, 'aiorchestration'))}
            </div>
          </div>
        </div>

        {renderModels(aiOrchestrationCapabilities, 'aiorchestration')}
      </>
    </ChartCard>
  );
};

export default AIOrchestration;
