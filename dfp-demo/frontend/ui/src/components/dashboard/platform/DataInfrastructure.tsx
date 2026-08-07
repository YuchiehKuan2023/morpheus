import { type FC } from 'react';
import { Activity, X } from 'lucide-react';
import type { GraphStats } from '@/types/graph';
import type { PlatformStats } from '@/types/dashboard';
import { Badge, KPICard } from '@/components';
import { ChartCard } from '..';
import { DASHBOARD_LAYOUT as DESC, getDatabases } from '@/constants/dashboard';

interface Props {
  graphStats?: GraphStats | null;
  platformStats?: PlatformStats | null;
  expandedCapability: string | null;
  toggleCapability: (key: string) => void;
}

const DataInfrastructure: FC<Props> = ({
  graphStats,
  platformStats,
  expandedCapability,
  toggleCapability,
}) => {
  const { title, description } = DESC.platformArchitecture.components.dataInfrastructure;

  const monitoredUsers = platformStats?.monitoredUsers?.toLocaleString() ?? '—';
  const qdrantDocs = platformStats?.qdrantDocuments?.toLocaleString() ?? '—';
  const databases = getDatabases({
    graphStats,
    platformStats,
    qdrantDocs,
    monitoredUsers,
  });

  return (
    <ChartCard
      title={title}
      description={
        <>
          <p className="text-xs text-muted-foreground mb-4 h-12">{description}</p>
          <div className="flex gap-2">
            <Badge variant="lime">PostgreSQL</Badge>
            <Badge variant="lime">Neo4j</Badge>
            <Badge variant="lime">Qdrant</Badge>
            <Badge variant="lime">Redis</Badge>
            <Badge variant="lime">MLflow</Badge>
          </div>
        </>
      }
      className="no-border no-shadow capability-card capability-card--with-models glass-card--xs"
    >
      <>
        <div className="capability-card__main-content">
          <div className="grid grid-cols-2 gap-2 pb-7 pt-3">
            <KPICard title="Monitored Users" value={monitoredUsers} size="xs" variant="dark" />
            <KPICard
              title="Vector Docs"
              value={qdrantDocs}
              size="xs"
              className="no-border no-shadow"
            />
          </div>

          <div className="platform-capabilities-list">
            <div>
              {databases.map(({ key, Icon, name, subtitle, details }) => {
                const isExpanded = expandedCapability === key;
                return (
                  <button
                    key={key}
                    className={`platform-capability__listing platform-capability__listing--clickable${isExpanded ? ' platform-capability__listing--active' : ''}`}
                    onClick={() => toggleCapability(key)}
                  >
                    <div className="platform-capability__icon">
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="platform-capability__info">
                      <div className="platform-capability__name">{name}</div>
                      <div className="platform-capability__description">{subtitle}</div>
                    </div>
                    <div className="platform-capability__badges">
                      <span className="platform-capability__model-count">
                        <Activity className="h-3 w-3" />
                        {details.length}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="platform-models-stack">
          {databases.map(({ key, Icon, name, subtitle, description, details }) => {
            const isExpanded = expandedCapability === key;
            return (
              <div key={key} className="platform-models-container">
                <div
                  className={`platform-models-panel ${isExpanded ? 'platform-models-panel--expanded' : ''}`}
                >
                  <div className="platform-models-panel__header">
                    <div className="flex items-center gap-2">
                      <div className="platform-capability__icon platform-capability__icon--sm">
                        <Icon className="h-3.5 w-3.5" />
                      </div>
                      <span className="platform-models-panel__title">{name}</span>
                    </div>
                    <button
                      className="platform-models-panel__close"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleCapability(key);
                      }}
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="platform-models-panel__content">
                    <div className="platform-model">
                      <div className="platform-model__header">
                        <div className="platform-model__icon">
                          <Icon className="h-5 w-5" />
                        </div>
                        <div className="platform-model__info">
                          <div className="platform-model__title">{name}</div>
                          <div className="platform-model__subtitle">{subtitle}</div>
                        </div>
                      </div>
                      <div className="platform-model__description">{description}</div>
                      <div className="platform-model__details">
                        {details.map(({ Icon: DetailIcon, label, value }) => (
                          <div key={label} className="platform-model__detail">
                            <DetailIcon className="h-3.5 w-3.5" />
                            <span className="platform-model__detail-label">{label}:</span>
                            <span className="platform-model__detail-value">{value}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </>
    </ChartCard>
  );
};

export default DataInfrastructure;
