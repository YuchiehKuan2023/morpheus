import {
  AnomalyActivity,
  AnomalyPattern,
  DashboardStats,
  Forecasting,
  GridCols,
  Investigation,
  PageHeader,
  PlatformOverview,
  RiskDistribution,
  SectionHeading,
  Spinner,
  SystemMaturity,
  TopRootCauses,
  Users,
} from '@/components';
import { useDashboard } from '@/hooks';
import { PAGE_HEADER } from '@/constants/shared';
import { DASHBOARD_LAYOUT as DESC } from '@/constants/dashboard';

export default function Dashboard() {
  const {
    stats,
    statsTrend,
    activityHeatmap,
    intradayRhythm,
    investigationTrend,
    systemMaturity,
    usersStats,
    riskDistributionData,
    topRootCausesData,
    loading,
  } = useDashboard();
  const { title, description } = PAGE_HEADER.dashboard;

  // Extract section descriptions for each dashboard section
  const intelligence = DESC.anomalyIntelligence.section;
  const operational = DESC.operationalPatterns.section;
  const risk = DESC.riskAndUserAnalysis.section;
  const trend = DESC.trendForecasting.section;
  const platform = DESC.platformArchitecture.section;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader {...{ title, description }} />

      {/* Key Performance Indicators */}
      <DashboardStats stats={stats} trend={statsTrend} />

      <SectionHeading title={intelligence.title} subtitle={intelligence.subtitle} />

      <GridCols cols={3}>
        {/* System Maturity — fixed width so heatmap fills remaining space */}
        <SystemMaturity {...{ systemMaturity }} />
        {/* Activity Heatmap */}
        <div className="col-span-2">
          <AnomalyActivity {...{ activityHeatmap }} />
        </div>
      </GridCols>

      <SectionHeading title={operational.title} subtitle={operational.subtitle} />

      <GridCols cols={2}>
        {/* Anomaly Pattern */}
        <AnomalyPattern {...{ intradayRhythm }} />
        {/* Investigation Throughput */}
        <Investigation {...{ investigationTrend }} />
      </GridCols>

      <SectionHeading title={risk.title} subtitle={risk.subtitle} />

      <GridCols cols={3}>
        <div className="col-span-2">
          {/* Top Users by Anomaly Volume */}
          <Users {...usersStats} />
        </div>

        <div className="flex flex-col gap-4">
          {/* Risk Distribution Breakdown */}
          <RiskDistribution {...{ riskDistributionData }} />
          {/* Top Root Causes Breakdown */}
          <TopRootCauses {...{ topRootCausesData }} />
        </div>
      </GridCols>

      <SectionHeading title={trend.title} subtitle={trend.subtitle} />

      {/* Trend Forecasting Chart */}
      <Forecasting />

      <SectionHeading title={platform.title} subtitle={platform.subtitle} />

      {/* Platform Capabilities */}
      <PlatformOverview />
    </div>
  );
}
