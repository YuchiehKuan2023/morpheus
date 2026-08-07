/**
 * PlatformOverview Component
 *
 * 6-card carousel — 3 visible at once, scrolls one card at a time.
 *
 * @module components/dashboard/PlatformOverview
 */

import { type FC, useState } from 'react';
import {
  DFPCore,
  AIOrchestration,
  MultiAgentSystem,
  GraphNetwork,
  ConversationalAi,
  DataInfrastructure,
  RagPipeline,
  createCapabilityRenderers,
} from './platform';
import { usePlatformStats, useGraph } from '@/hooks';
import { ChevronLeft, ChevronRight } from 'lucide-react';

const TOTAL_CARDS = 7;
const VISIBLE = 3;
const MAX_INDEX = TOTAL_CARDS - VISIBLE; // 4 — last position shows cards 5·6·7

const PlatformOverview: FC = () => {
  const { platformStats } = usePlatformStats();
  const { stats: graphStats } = useGraph();

  const [expandedCapability, setExpandedCapability] = useState<string | null>(null);
  const [slideIndex, setSlideIndex] = useState(0);

  const toggleCapability = (capabilityName: string) => {
    setExpandedCapability(expandedCapability === capabilityName ? null : capabilityName);
  };

  const { renderListing, renderModels } = createCapabilityRenderers(
    expandedCapability,
    toggleCapability
  );

  // Infinite wrap within the 4 meaningful positions (0–3)
  const goTo = (i: number) =>
    setSlideIndex(((i % (MAX_INDEX + 1)) + (MAX_INDEX + 1)) % (MAX_INDEX + 1));

  // Track is 7/3 viewports wide (7 items × 1/3 viewport); each step shifts 1/7 of track = 1/3 viewport
  const translateX = `${-(slideIndex * (100 / TOTAL_CARDS))}%`;

  return (
    <section>
      <div className="platform-overview__carousel">
        {/* Arrow — previous */}
        <button
          className="platform-overview__arrow platform-overview__arrow--prev"
          onClick={() => goTo(slideIndex - 1)}
          aria-label="Previous card"
        >
          <ChevronLeft width={18} height={18} />
        </button>

        {/* Viewport */}
        <div className="platform-overview__viewport">
          <div
            className="platform-overview__track"
            style={{ transform: `translateX(${translateX})` }}
          >
            <div className="platform-overview__item">
              <DFPCore
                platformStats={platformStats}
                renderListing={renderListing}
                renderModels={renderModels}
              />
            </div>
            <div className="platform-overview__item">
              <AIOrchestration
                platformStats={platformStats}
                renderListing={renderListing}
                renderModels={renderModels}
              />
            </div>
            <div className="platform-overview__item">
              <MultiAgentSystem
                platformStats={platformStats}
                renderListing={renderListing}
                renderModels={renderModels}
              />
            </div>
            <div className="platform-overview__item">
              <GraphNetwork
                graphStats={graphStats}
                expandedCapability={expandedCapability}
                toggleCapability={toggleCapability}
                renderListing={renderListing}
              />
            </div>
            <div className="platform-overview__item">
              <ConversationalAi
                vectorDocuments={platformStats?.qdrantDocuments}
                renderListing={renderListing}
                renderModels={renderModels}
              />
            </div>
            <div className="platform-overview__item">
              <RagPipeline
                vectorDocuments={platformStats?.qdrantDocuments}
                renderListing={renderListing}
                renderModels={renderModels}
              />
            </div>
            <div className="platform-overview__item">
              <DataInfrastructure
                graphStats={graphStats}
                platformStats={platformStats}
                expandedCapability={expandedCapability}
                toggleCapability={toggleCapability}
              />
            </div>
          </div>
        </div>

        {/* Arrow — next */}
        <button
          className="platform-overview__arrow platform-overview__arrow--next"
          onClick={() => goTo(slideIndex + 1)}
          aria-label="Next card"
        >
          <ChevronRight width={18} height={18} />
        </button>

        {/* Pagination dots — one per stop */}
        <div className="platform-overview__dots">
          {Array.from({ length: MAX_INDEX + 1 }).map((_, i) => (
            <button
              key={i}
              className={`platform-overview__dot${i === slideIndex ? ' platform-overview__dot--active' : ''}`}
              onClick={() => goTo(i)}
              aria-label={`Go to position ${i + 1}`}
            />
          ))}
        </div>
      </div>
    </section>
  );
};

export default PlatformOverview;
