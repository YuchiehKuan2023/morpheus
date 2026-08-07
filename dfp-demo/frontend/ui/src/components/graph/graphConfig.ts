import type { NodeLabel } from '@/types';

// Pastel fill colours (used for circle fill + legend swatches)
export const NODE_COLORS: Record<NodeLabel, string> = {
  User: '#a5b4fc', // indigo-300
  Detection: '#fca5a5', // red-300
  Application: '#fcd34d', // amber-300
  Device: '#6ee7b7', // emerald-300
  Browser: '#93c5fd', // blue-300
  OperatingSystem: '#c4b5fd', // violet-300
  IPAddress: '#f9a8d4', // pink-300
  ClientApp: '#5eead4', // teal-300
  Location: '#fdba74', // orange-300
  Unknown: '#d1d5db', // gray-300
};

// Saturated stroke/border colours matching each pastel fill
export const NODE_BORDER_COLORS: Record<NodeLabel, string> = {
  User: '#ffffff',
  Detection: '#ffffff',
  Application: '#ffffff',
  Device: '#ffffff',
  Browser: '#ffffff',
  OperatingSystem: '#ffffff',
  IPAddress: '#ffffff',
  ClientApp: '#ffffff',
  Location: '#ffffff',
  Unknown: '#ffffff',
};

export const NODE_SIZES: Record<NodeLabel, number> = {
  User: 10,
  Detection: 7,
  Application: 8,
  Device: 6,
  Browser: 5,
  OperatingSystem: 5,
  IPAddress: 5,
  ClientApp: 5,
  Location: 6,
  Unknown: 4,
};

export const LABEL_DESCRIPTIONS: Record<NodeLabel, string> = {
  User: 'Monitored users',
  Detection: 'DFP anomaly detections',
  Application: 'Accessed applications (O365, Salesforce...)',
  Device: 'Endpoint devices',
  Browser: 'Web browsers',
  OperatingSystem: 'Operating systems',
  IPAddress: 'Source IP addresses',
  ClientApp: 'Auth clients (POP3, EWS…)',
  Location: 'Geographic locations',
  Unknown: 'Unrecognised node type',
};
