import { type FC, type ReactElement } from 'react';
import { type Capability, conversationalCapabilities, PLATFORM_STATS } from '.';
import { Badge, KPICard } from '@/components';
import { ChartCard } from '..';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  vectorDocuments?: number;
  renderListing: (capability: Capability, sectionKey: string) => ReactElement;
  renderModels: (capabilities: Capability[], sectionKey: string) => ReactElement | null;
}

const ConversationalAi: FC<Props> = ({ vectorDocuments, renderListing, renderModels }) => {
  const { title, description } = DESC.platformArchitecture.components.conversationalAi;

  return (
    <ChartCard
      title={title}
      description={
        <>
          <p className="text-xs text-muted-foreground mb-4 h-12">{description}</p>
          <div className="flex gap-2">
            <Badge>RAG-powered analyst assistant</Badge>
            <Badge variant="lime">GitHub Models</Badge>
            <Badge variant="lime">Qdrant</Badge>
          </div>
        </>
      }
      className="no-border no-shadow capability-card capability-card--with-models glass-card--xs"
    >
      <>
        <div className="capability-card__main-content">
          <div className="grid grid-cols-2 gap-2 pb-7 pt-3">
            <KPICard
              title="Documents"
              value={(vectorDocuments ?? PLATFORM_STATS.qdrantDocuments).toLocaleString()}
              size="xs"
              variant="dark"
            />
            <KPICard
              title="Collections"
              value={PLATFORM_STATS.qdrantCollections}
              size="xs"
              className="no-border no-shadow"
            />
          </div>

          <div className="platform-capabilities-list">
            <div>
              {conversationalCapabilities.map((cap) => renderListing(cap, 'conversational'))}
            </div>
          </div>
        </div>

        {renderModels(conversationalCapabilities, 'conversational')}
      </>
    </ChartCard>
  );
};

export default ConversationalAi;
