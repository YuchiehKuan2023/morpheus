import { type FC, type ReactElement } from 'react';
import type { GraphStats } from '@/types/graph';
import { type Capability, graphCapabilities } from '.';
import { GitBranch, GitCompare, GitGraph, X } from 'lucide-react';
import { Badge, KPICard } from '@/components';
import { ChartCard } from '..';
import { renderModelPanel } from './utils';
import { toTitleCase } from '@/utils';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

const REL_KEY = 'graph-RelationshipTypes';

interface Props {
  graphStats?: GraphStats | null;
  expandedCapability: string | null;
  toggleCapability: (key: string) => void;
  renderListing: (capability: Capability, sectionKey: string) => ReactElement;
}

const GraphNetwork: FC<Props> = ({
  graphStats,
  expandedCapability,
  toggleCapability,
  renderListing,
}) => {
  const { title, description } = DESC.platformArchitecture.components.graphNetwork;

  const nodes = graphStats?.total_nodes?.toLocaleString() ?? '—';
  const relationships = graphStats?.total_relationships?.toLocaleString() ?? '—';

  const relEntries = graphStats?.relationship_counts
    ? Object.entries(graphStats.relationship_counts).sort(([, a], [, b]) => b - a)
    : [];

  const total = Math.max(graphStats?.total_relationships ?? 0, 1);
  const isRelExpanded = expandedCapability === REL_KEY;

  return (
    <ChartCard
      title={title}
      description={
        <>
          <p className="text-xs text-muted-foreground mb-4 h-12">{description}</p>
          <div className="flex gap-2">
            <Badge>Neo4j knowledge graph</Badge>
            <Badge variant="lime">9 node types</Badge>
            <Badge variant="lime">8 rel. types</Badge>
          </div>
        </>
      }
      className="no-border no-shadow capability-card capability-card--with-models glass-card--xs"
    >
      <>
        <div className="capability-card__main-content">
          <div className="grid grid-cols-2 gap-2 pb-7 pt-3">
            <KPICard title="Nodes" value={nodes} size="xs" variant="dark" />
            <KPICard
              title="Relationships"
              value={relationships}
              size="xs"
              className="no-border no-shadow"
            />
          </div>

          <div className="platform-capabilities-list">
            <div>
              {graphCapabilities.map((cap) => renderListing(cap, 'graph'))}

              {/* Relationship Types — expandable listing row */}
              {relEntries.length > 0 && (
                <button
                  className="platform-capability__listing platform-capability__listing--clickable"
                  onClick={() => toggleCapability(REL_KEY)}
                >
                  <div className="platform-capability__icon">
                    <GitBranch className="h-4 w-4" />
                  </div>
                  <div className="platform-capability__info">
                    <div className="platform-capability__name">Relationship Types</div>
                    <div className="platform-capability__description">
                      {relEntries.length} types across the knowledge graph
                    </div>
                  </div>
                  <div className="platform-capability__badges">
                    <span className="platform-capability__model-count">
                      <GitGraph className="h-3 w-3" />
                      {relEntries.length}
                    </span>
                  </div>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Bottom panels — model panels + relationship types panel */}
        <div className="platform-models-stack">
          {graphCapabilities.map((cap) =>
            renderModelPanel(cap, 'graph', expandedCapability, toggleCapability)
          )}

          {/* Relationship Types expanded panel */}
          {relEntries.length > 0 && (
            <div className="platform-models-container">
              <div
                className={`platform-models-panel ${isRelExpanded ? 'platform-models-panel--expanded' : ''}`}
              >
                <div className="platform-models-panel__header">
                  <div className="flex items-center gap-2">
                    <div className="platform-capability__icon platform-capability__icon--sm">
                      <GitBranch className="h-3.5 w-3.5" />
                    </div>
                    <span className="platform-models-panel__title">Relationship Types</span>
                  </div>
                  <button
                    className="platform-models-panel__close"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleCapability(REL_KEY);
                    }}
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <div className="platform-models-panel__content">
                  <div className="platform-model">
                    <div className="platform-model__header">
                      <div className="platform-model__icon">
                        <GitBranch className="h-5 w-5" />
                      </div>
                      <div className="platform-model__info">
                        <div className="platform-model__title">Neo4j Relationship Types</div>
                        <div className="platform-model__subtitle">
                          {relEntries.length} types · {relationships} total
                        </div>
                      </div>
                    </div>
                    <div className="platform-model__description">
                      Each relationship connects a User node to an entity in the knowledge graph,
                      enabling attack-chain traversal and behavioural correlation.
                    </div>
                    <div className="platform-model__details">
                      {relEntries.map(([type, count]) => {
                        const pct = ((count / total) * 100).toFixed(1);
                        const label = type
                          .split('_')
                          .map((w) =>
                            toTitleCase(w).replace('Os', 'Operating System').replace('Ip', 'IP')
                          )
                          .join(' ');

                        return (
                          <div key={type} className="platform-model__detail">
                            <GitCompare className="h-3.5 w-3.5 shrink-0" />
                            <span className="platform-model__detail-label">{label}</span>
                            <span className="platform-model__detail-value">
                              {count.toLocaleString()} ({pct}%)
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </>
    </ChartCard>
  );
};

export default GraphNetwork;
