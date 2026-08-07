import { type FC, type ReactElement } from 'react';
import { ChartCard } from '..';
import { Badge, KPICard } from '@/components';
import { multiAgentCapabilities, type Capability } from '.';
import type { PlatformStats } from '@/types/dashboard';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  platformStats?: PlatformStats | null;
  renderListing: (capability: Capability, sectionKey: string) => ReactElement;
  renderModels: (capabilities: Capability[], sectionKey: string) => ReactElement | null;
}

const MultiAgentSystem: FC<Props> = ({ platformStats, renderListing, renderModels }) => {
  const { title, description } = DESC.platformArchitecture.components.multiAgentSystem;

  return (
    <ChartCard
      title={title}
      description={
        <>
          <p className="text-xs text-muted-foreground mb-4 h-12">{description}</p>
          <div className="flex gap-2">
            <Badge>Autonomous</Badge>
            <Badge variant="lime">Forensics</Badge>
            <Badge variant="lime">Investigation</Badge>
            <Badge variant="lime">Remediation</Badge>
          </div>
        </>
      }
      className="no-border no-shadow capability-card capability-card--with-models glass-card--xs"
    >
      <>
        <div className="capability-card__main-content">
          <div className="grid grid-cols-2 gap-2 pb-7 pt-3">
            <KPICard
              title="Investigations"
              value={
                platformStats != null ? platformStats.totalInvestigations.toLocaleString() : '—'
              }
              size="xs"
              variant="dark"
            />
            <KPICard
              title="Findings"
              value={platformStats != null ? platformStats.totalFindings.toLocaleString() : '—'}
              size="xs"
              className="no-border no-shadow"
            />
          </div>

          <div className="platform-capabilities-list">
            <div>{multiAgentCapabilities.map((cap) => renderListing(cap, 'multiagent'))}</div>
          </div>
        </div>

        {renderModels(multiAgentCapabilities, 'multiagent')}
      </>
    </ChartCard>
  );
};

export default MultiAgentSystem;
