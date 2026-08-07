import { INITIAL_STATE, REFRESH_INTERVAL } from '@/constants';
import { api } from '@/services/api';
import type { DashboardState, RiskDistributionData, RootCauseData } from '@/types';
import { useCallback, useEffect, useState, startTransition } from 'react';
import type { CarouselApi } from '@/components/ui';
import { formatDate } from '@/utils';

function useDashboard() {
  const [state, setState] = useState<DashboardState>(INITIAL_STATE);
  const [carouselApi, setCarouselApi] = useState<CarouselApi>();

  const loadData = useCallback(async () => {
    try {
      const snapshot = await api.getDashboardSnapshot();
      startTransition(() => {
        setState({
          stats: snapshot.stats,
          statsTrend: snapshot.statsTrend,
          recentAnomalies: snapshot.recentAnomalies,
          riskDistribution: snapshot.riskDistribution,
          topAnomalies: snapshot.topAnomalies,
          topUsers: snapshot.topUsers,
          topRootCauses: snapshot.topRootCauses,
          activityHeatmap: snapshot.activityHeatmap,
          userMetrics: snapshot.userMetrics,
          systemMaturity: snapshot.systemMaturity,
          intradayRhythm: snapshot.intradayRhythm,
          investigationTrend: snapshot.investigationTrend,
          loading: false,
        });
      });
    } catch (err) {
      console.error('Dashboard snapshot load failed:', err);
      startTransition(() => {
        setState((prev) => ({ ...prev, loading: false }));
      });
    }
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [loadData]);

  const statusStats = {
    new: state.stats?.anomalies.new ?? 0,
    resolved: state.stats?.anomalies.resolved ?? 0,
    pending: state.stats?.anomalies.pending ?? 0,
  };

  const usersStats = {
    statusStats,
    topUsers: state.topUsers,
    userMetrics: state.userMetrics,
    carouselApi,
    setCarouselApi,
  };

  const riskDistributionData: RiskDistributionData[] = [
    { label: 'critical', value: state.riskDistribution.critical },
    { label: 'high', value: state.riskDistribution.high, active: true },
    { label: 'medium', value: state.riskDistribution.medium },
    { label: 'low', value: state.riskDistribution.low },
  ];

  const topRootCausesData: RootCauseData[] = state.topRootCauses.map((rc) => ({
    label: rc.root_cause,
    value: rc.anomaly_count,
    active: rc === state.topRootCauses[0],
    meta: {
      Anomalies: rc.anomaly_count,
      'Affected users': rc.affected_users,
      'Avg score': rc.avg_anomaly_score,
      'Avg risk score': rc.avg_risk_score,
      Critical: rc.critical_count,
      High: rc.high_count,
      Medium: rc.medium_count,
      'Last seen': formatDate(rc.last_seen_at),
    },
  }));

  return {
    ...state,
    usersStats,
    riskDistributionData,
    topRootCausesData,
  };
}

export default useDashboard;
