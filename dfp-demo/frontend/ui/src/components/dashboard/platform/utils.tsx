import { List, Sparkles, X } from 'lucide-react';
import type { Capability } from './types';

/**
 * Render capability listing (without inline model expansion)
 */
export const renderCapabilityListing = (
  capability: Capability,
  sectionKey: string,
  expandedCapability: string | null,
  toggleCapability: (capabilityName: string) => void
) => {
  const hasModels = capability.models.length > 0;
  const hasTools = (capability.tools?.length ?? 0) > 0;
  const hasContent = hasModels || hasTools;
  const capabilityKey = `${sectionKey}-${capability.name}`;
  const isExpanded = expandedCapability === capabilityKey;

  return (
    <button
      key={capability.name}
      className={`platform-capability__listing ${hasContent ? 'platform-capability__listing--clickable' : ''} ${isExpanded ? 'platform-capability__listing--active' : ''}`}
      onClick={() => hasContent && toggleCapability(capabilityKey)}
      disabled={!hasContent}
    >
      <div className="platform-capability__icon">
        <capability.icon className="h-4 w-4" />
      </div>
      <div className="platform-capability__info">
        <div className="platform-capability__name">{capability.name}</div>
        <div className="platform-capability__description">{capability.description}</div>
      </div>
      <div className="platform-capability__badges">
        {hasTools && (
          <span className="platform-capability__model-count">
            <List className="h-3 w-3" />
            {capability.tools!.length}
          </span>
        )}
        {hasModels && (
          <span className="platform-capability__model-count">
            <Sparkles className="h-3 w-3" />
            {capability.models.length}
          </span>
        )}
      </div>
    </button>
  );
};

/**
 * Render a single model panel container (collapsed/expanded) for one capability.
 * No preview button — the panel is only triggered from the listing row above.
 */
export const renderModelPanel = (
  capability: Capability,
  sectionKey: string,
  expandedCapability: string | null,
  toggleCapability: (key: string) => void
) => {
  const hasModels = capability.models.length > 0;
  const hasTools = (capability.tools?.length ?? 0) > 0;
  if (!hasModels && !hasTools) return null;

  const capabilityKey = `${sectionKey}-${capability.name}`;
  const isExpanded = expandedCapability === capabilityKey;

  return (
    <div key={capability.name} className="platform-models-container">
      <div
        className={`platform-models-panel ${isExpanded ? 'platform-models-panel--expanded' : ''}`}
      >
        <div className="platform-models-panel__header">
          <div className="flex items-center gap-2">
            <div className="platform-capability__icon platform-capability__icon--sm">
              <capability.icon className="h-3.5 w-3.5" />
            </div>
            <span className="platform-models-panel__title">{capability.name}</span>
          </div>
          <button
            className="platform-models-panel__close"
            onClick={(e) => {
              e.stopPropagation();
              toggleCapability(capabilityKey);
            }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="platform-models-panel__content">
          {hasModels &&
            capability.models.map((model) => (
              <div key={model.title} className="platform-model">
                <div className="platform-model__header">
                  <div className="platform-model__icon">
                    <model.icon className="h-5 w-5" />
                  </div>
                  <div className="platform-model__info">
                    <div className="platform-model__title">{model.title}</div>
                    <div className="platform-model__subtitle">{model.subtitle}</div>
                  </div>
                </div>
                <div className="platform-model__description">{model.description}</div>
                <div className="platform-model__details">
                  {model.details.map((detail, idx) => (
                    <div key={idx} className="platform-model__detail">
                      <detail.icon className="h-3.5 w-3.5" />
                      <span className="platform-model__detail-label">{detail.label}:</span>
                      <span className="platform-model__detail-value">{detail.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          {hasTools && (
            <div className="platform-tools-list">
              {capability.tools!.map((tool) => (
                <div key={tool.name} className="platform-tool">
                  <div className="platform-tool__name">{tool.name}</div>
                  <div className="platform-tool__description">{tool.description}</div>
                  <div className="platform-tool__source">{tool.source}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

/**
 * Render stacked model panels at the bottom of a card.
 * Preview (collapsed) buttons are intentionally omitted — panels are only
 * triggered by the listing row sparkle icon at the top of the card.
 */
export const renderModelSections = (
  capabilities: Capability[],
  sectionKey: string,
  expandedCapability: string | null,
  toggleCapability: (capabilityName: string) => void
) => {
  const capabilitiesWithContent = capabilities.filter(
    (cap) => cap.models.length > 0 || (cap.tools?.length ?? 0) > 0
  );

  if (capabilitiesWithContent.length === 0) return null;

  return (
    <div className="platform-models-stack">
      {capabilitiesWithContent.map((cap) =>
        renderModelPanel(cap, sectionKey, expandedCapability, toggleCapability)
      )}
    </div>
  );
};

/**
 * Creates a capability card renderer with access to expansion state and toggle function.
 * This is a higher-order function that returns the actual render functions.
 */
export const createCapabilityRenderers = (
  expandedCapability: string | null,
  toggleCapability: (capabilityName: string) => void
) => {
  return {
    renderListing: (capability: Capability, sectionKey: string) =>
      renderCapabilityListing(capability, sectionKey, expandedCapability, toggleCapability),
    renderModels: (capabilities: Capability[], sectionKey: string) =>
      renderModelSections(capabilities, sectionKey, expandedCapability, toggleCapability),
  };
};
