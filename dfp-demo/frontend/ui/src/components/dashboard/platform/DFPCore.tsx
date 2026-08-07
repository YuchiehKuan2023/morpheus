import { type FC, type ReactElement } from 'react';
import { ChartCard } from '..';
import { Badge, KPICard } from '@/components';
import { dfpCoreCapabilities, type Capability } from '.';
import type { PlatformStats } from '@/types/dashboard';
import NvidiaLogo from '../../../assets/nvidia-logo.svg';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

interface Props {
  platformStats?: PlatformStats | null;
  renderListing: (capability: Capability, sectionKey: string) => ReactElement;
  renderModels: (capabilities: Capability[], sectionKey: string) => ReactElement | null;
}

const DFPCore: FC<Props> = ({ platformStats, renderListing, renderModels }) => {
  const { title, description } = DESC.platformArchitecture.components.dfpCoreEngine;

  return (
    <ChartCard
      title={
        <span className="flex items-center gap-2 relative">
          <img
            src={NvidiaLogo}
            alt="NVIDIA Logo"
            className="nvidia-logo w-8 h-8 absolute"
            title="NVIDIA"
          />
          <span className="ml-10">{title}</span>
        </span>
      }
      description={
        <>
          <p className="text-xs text-muted-foreground mb-4 h-12">{description}</p>
          <div className="flex gap-2">
            <Badge>NVIDIA Morpheus</Badge>
            <Badge variant="lime">training</Badge>
            <Badge variant="lime">inference</Badge>
            <Badge variant="lime">feedback-loop</Badge>
          </div>
        </>
      }
      className="no-border no-shadow capability-card capability-card--with-models glass-card--xs"
    >
      <>
        <div className="capability-card__main-content">
          <div className="grid grid-cols-2 gap-2 pb-7 pt-3">
            <KPICard
              title="Users Monitored"
              value={platformStats?.monitoredUsers ?? '—'}
              size="xs"
              variant="dark"
            />
            <KPICard
              title="Detections"
              value={platformStats != null ? platformStats.totalDetections.toLocaleString() : '—'}
              size="xs"
              className="no-border no-shadow"
            />
          </div>

          <div className="platform-capabilities-list">
            <div>{dfpCoreCapabilities.map((cap) => renderListing(cap, 'dfpcore'))}</div>
          </div>
        </div>

        {renderModels(dfpCoreCapabilities, 'dfpcore')}
      </>
    </ChartCard>
  );
};

export default DFPCore;
