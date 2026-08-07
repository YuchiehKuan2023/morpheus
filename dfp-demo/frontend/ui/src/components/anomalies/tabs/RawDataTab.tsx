import type { FC } from 'react';
import { useState } from 'react';
import { Copy, Check } from 'lucide-react';

interface Props {
  originalEvent: Record<string, unknown> | null;
  aiEnrichment: Record<string, unknown> | null;
  rawDetection: Record<string, unknown> | null;
}

function JsonPanel({ label, data }: { label: string; data: Record<string, unknown> | null }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(data ?? null, null, 2);

  function handleCopy(e: React.MouseEvent) {
    e.stopPropagation();
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <details className="anom-raw-panel">
      <summary className="anom-raw-panel__summary">
        <span className="anom-raw-panel__label">{label}</span>
        <button
          type="button"
          className="anom-raw-panel__copy"
          onClick={handleCopy}
          title="Copy JSON"
          aria-label={`Copy ${label} JSON`}
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-green-500" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </button>
      </summary>
      <pre className="anom-raw-panel__code">{data == null ? 'null' : text}</pre>
    </details>
  );
}

export const RawDataTab: FC<Props> = ({ originalEvent, aiEnrichment, rawDetection }) => (
  <div className="space-y-3">
    <JsonPanel label="Original Event" data={originalEvent} />
    <JsonPanel label="AI Enrichment" data={aiEnrichment} />
    <JsonPanel label="Raw Detection" data={rawDetection} />
  </div>
);
