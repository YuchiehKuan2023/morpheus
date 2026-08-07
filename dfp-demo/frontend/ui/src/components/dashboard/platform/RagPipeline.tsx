import { type FC, type ReactElement } from 'react';
import { ChartCard } from '..';
import { Badge, KPICard } from '@/components';
import { ragCapabilities, type Capability } from '.';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  vectorDocuments?: number;
  renderListing: (capability: Capability, sectionKey: string) => ReactElement;
  renderModels: (capabilities: Capability[], sectionKey: string) => ReactElement | null;
}

const RagPipeline: FC<Props> = ({ vectorDocuments, renderListing, renderModels }) => {
  const { title, description } = DESC.platformArchitecture.components.ragPipeline;

  return (
    <ChartCard
      title={title}
      description={
        <>
          <p className="text-xs text-muted-foreground mb-4 h-12">{description}</p>
          <div className="flex gap-2">
            <Badge>Context assembly</Badge>
            <Badge variant="lime">Qdrant</Badge>
            <Badge variant="lime">Neo4j</Badge>
            <Badge variant="lime">MiniLM-L6-v2</Badge>
          </div>
        </>
      }
      className="no-border no-shadow capability-card capability-card--with-models glass-card--xs"
    >
      <>
        <div className="capability-card__main-content">
          <div className="grid grid-cols-2 gap-2 pb-7 pt-3">
            <KPICard
              title="Vector docs"
              value={vectorDocuments?.toLocaleString() ?? '—'}
              size="xs"
              variant="dark"
            />
            <KPICard
              title="Embedding dim"
              value="384-D"
              size="xs"
              className="no-border no-shadow"
            />
          </div>

          <div className="platform-capabilities-list">
            <div>{ragCapabilities.map((cap) => renderListing(cap, 'rag'))}</div>
          </div>
        </div>

        {renderModels(ragCapabilities, 'rag')}
      </>
    </ChartCard>
  );
};

export default RagPipeline;
