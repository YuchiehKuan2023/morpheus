import { useEffect, useState, useCallback } from 'react';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { setAnomalies } from '../features/anomalies/anomaliesSlice';
import { api } from '../services/api';
import { AnomalyDetailSheet } from '../components';

export default function Anomalies() {
  const dispatch = useAppDispatch();
  const { items, filter } = useAppSelector((state) => state.anomalies);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const loadAnomalies = useCallback(async () => {
    try {
      const data = await api.getAnomalies();
      dispatch(setAnomalies(data));
    } catch (err) {
      console.error('Failed to load anomalies:', err);
    } finally {
      setLoading(false);
    }
  }, [dispatch]);

  useEffect(() => {
    loadAnomalies();
    const interval = setInterval(loadAnomalies, 5000);
    return () => clearInterval(interval);
  }, [loadAnomalies]);

  const filteredAnomalies = items.filter((anomaly) => {
    if (filter.severity.length > 0 && !filter.severity.includes(anomaly.severity)) {
      return false;
    }
    if (filter.status.length > 0 && !filter.status.includes(anomaly.status)) {
      return false;
    }
    return true;
  });

  const severityColors = {
    low: 'bg-blue-100 text-blue-800',
    medium: 'bg-yellow-100 text-yellow-800',
    high: 'bg-orange-100 text-orange-800',
    critical: 'bg-red-100 text-red-800',
  };

  const statusColors = {
    new: 'bg-blue-100 text-blue-800',
    pending: 'bg-yellow-100 text-yellow-800',
    resolved: 'bg-green-100 text-green-800',
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  function openSheet(id: string) {
    setSelectedId(id);
    setSheetOpen(true);
  }

  return (
    <div className="space-y-6">
      <AnomalyDetailSheet
        key={selectedId ?? undefined}
        anomalyId={selectedId}
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
      />
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Anomalies</h2>
          <p className="text-gray-600 mt-1">{filteredAnomalies.length} anomalies detected</p>
        </div>
        <button
          onClick={loadAnomalies}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          Refresh
        </button>
      </div>

      {/* Anomalies List */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  User
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Timestamp
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Score
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Risk
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Severity
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Event Type
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {filteredAnomalies.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-gray-500">
                    No anomalies detected yet. System is monitoring for suspicious behavior.
                  </td>
                </tr>
              ) : (
                filteredAnomalies.map((anomaly) => (
                  <tr
                    key={anomaly.id}
                    className="hover:bg-gray-50 transition-colors cursor-pointer"
                    onClick={() => openSheet(anomaly.id)}
                  >
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="font-medium text-gray-900">{anomaly.username}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(anomaly.timestamp).toLocaleString()}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="font-mono text-sm font-medium">
                        {anomaly.anomalyScore.toFixed(3)}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="font-mono text-sm font-medium">
                        {anomaly.riskScore != null ? Math.round(anomaly.riskScore) : '—'}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full ${
                          severityColors[anomaly.severity]
                        }`}
                      >
                        {anomaly.severity}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span
                        className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full ${
                          statusColors[anomaly.status]
                        }`}
                      >
                        {anomaly.status.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {anomaly.eventType}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
