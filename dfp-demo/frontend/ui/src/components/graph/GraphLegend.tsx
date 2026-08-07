import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { NODE_COLORS } from './graphConfig';

const NODE_TYPES = [
  { label: 'User', desc: 'Monitored employee accounts' },
  { label: 'Detection', desc: 'DFP anomaly events' },
  { label: 'Application', desc: 'Apps accessed (O365, Salesforce…)' },
  { label: 'Device', desc: 'Endpoint devices' },
  { label: 'Browser', desc: 'Web browsers' },
  { label: 'OperatingSystem', desc: 'Operating systems' },
  { label: 'IPAddress', desc: 'Source IP addresses' },
  { label: 'ClientApp', desc: 'Auth clients (POP3, EWS…)' },
  { label: 'Location', desc: 'Geographic locations' },
] as const;

export default function GraphLegend() {
  const [open, setOpen] = useState(true);

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-lg w-48">
      {/* Header */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2.5 text-gray-800 hover:bg-gray-50 transition-colors"
      >
        <span className="text-xs font-semibold text-gray-900">Graph Legend</span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>

      {open && (
        <div className="px-3 pb-3 flex flex-col gap-3 text-xs">
          {/* Node types */}
          <div>
            <p className="text-[10px] font-medium text-gray-500 uppercase tracking-wider mb-1.5">
              Node Types
            </p>
            <div className="flex flex-col gap-1">
              {NODE_TYPES.map(({ label, desc }) => (
                <div key={label} className="flex items-center gap-2" title={desc}>
                  <span
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: NODE_COLORS[label as keyof typeof NODE_COLORS] }}
                  />
                  <span className="text-gray-700 truncate">{label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Interactions */}
          <div>
            <p className="text-[10px] font-medium text-gray-500 uppercase tracking-wider mb-1.5">
              Interactions
            </p>
            <ul className="flex flex-col gap-0.5 text-gray-400 text-[11px]">
              <li>· Click node to view details</li>
              <li>· Right-click to expand</li>
              <li>· Drag to pin position</li>
              <li>· Scroll to zoom</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
