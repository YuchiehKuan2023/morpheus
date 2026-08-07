/**
 * SHAPChart — horizontal bar chart showing top SHAP drivers and mitigators.
 *
 * Rendered as a 2-column grid using the shared BarChart component.
 * Both columns share the same scale (max across all entries) so bar lengths
 * are directly comparable.
 */
import BarChart from '@/components/common/BarChart';
import type { ShapEntry } from '@/types/simulation';

interface SHAPChartProps {
  topDrivers: ShapEntry[];
  topMitigators: ShapEntry[];
  /** Max entries to show per section; defaults to 5 */
  limit?: number;
}

export function SHAPChart({ topDrivers, topMitigators, limit = 5 }: SHAPChartProps) {
  const drivers = topDrivers.slice(0, limit);
  const mitigators = topMitigators.slice(0, limit);

  if (drivers.length === 0 && mitigators.length === 0) {
    return <p className="text-muted-foreground text-sm py-4 text-center">No SHAP data available</p>;
  }

  const driverData = drivers.map((e, i) => ({
    label: e.label,
    value: Math.abs(e.contribution),
    active: i === 0, // Highlight the top driver
  }));

  const mitigatorData = mitigators.map((e, i) => ({
    label: e.label,
    value: Math.abs(e.contribution),
    active: i === 0, // Highlight the top mitigator
  }));

  return (
    <div className="grid grid-cols-1 gap-6 pt-1">
      {drivers.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wider mb-6">Risk Drivers</h4>
          <div style={{ height: '250px' }} className="pt-3">
            <BarChart data={driverData} variant="default" />
          </div>
        </div>
      )}
      {mitigators.length > 0 && (
        <>
          <div className="separator -mr-4 -ml-4" />
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider mb-6">
              Mitigating Factors
            </h4>
            <div style={{ height: '250px' }} className="pt-3">
              <BarChart data={mitigatorData} variant="uniform" />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
