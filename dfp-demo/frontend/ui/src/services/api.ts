import type {
  Anomaly,
  AnomalyDetail,
  AnomalyExplanation,
  AnomalyInvestigation,
  AgentFinding,
  AnalystNotification,
  LlmExplanation,
  User,
  Detection,
  UserProfile,
  Stats,
  DashboardRecentAnomaly,
  DashboardSnapshot,
  RiskDistribution,
  TopUser,
  TopAnomaly,
  TopRootCause,
  HeatmapDay,
  UserMetrics,
  SystemMaturity,
  StatsTrend,
  IntradayRhythmCell,
  InvestigationTrendDay,
  UserTrendPoint,
  UserDetail,
  PaginatedUserAnomalies,
  PlatformStats,
  ForecastData,
  ForecastSummary,
  SimProcessEntry,
} from '@/types';
import { API, API_BASE_URL } from '@/constants';

class ApiService {
  private async fetchJson<T>(endpoint: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });

    if (response.status === 401) {
      window.dispatchEvent(new Event('auth:unauthorized'));
    }

    if (!response.ok) {
      throw new Error(`API error: ${response.statusText}`);
    }

    return response.json();
  }

  // Anomalies
  async getAnomalies(limit = 100): Promise<Anomaly[]> {
    const raw = await this.fetchJson<Record<string, unknown>[]>(API.anomalies.list(limit));
    return raw.map((r) => ({
      id: String(r.anomaly_id ?? r.id ?? ''),
      username: String(r.user_id ?? r.username ?? ''),
      timestamp: String(r.timestamp ?? ''),
      anomalyScore: Number(r.anomaly_score ?? r.anomalyScore ?? 0),
      eventType: String(
        (r.original_event as Record<string, unknown>)?.appDisplayName ??
          (r.original_event as Record<string, unknown>)?.event_type ??
          r.eventType ??
          r.root_cause ??
          'Unknown'
      ),
      details: (r.original_event as Record<string, unknown>) ?? {},
      severity: String(r.severity ?? 'low').toLowerCase() as Anomaly['severity'],
      status: (r.status ?? r.dfp_retrain_status ?? 'new') as Anomaly['status'],
      rootCause: (r.root_cause as string) ?? null,
      subCategory: (r.sub_category as string) ?? null,
      riskScore: r.risk_score != null ? Number(r.risk_score) : null,
      isAnomaly: (r.is_anomaly as boolean) ?? null,
      aiEnrichment: (r.ai_enrichment as Record<string, unknown>) ?? null,
      originalEvent: (r.original_event as Record<string, unknown>) ?? null,
      createdAt: (r.created_at as string) ?? null,
    }));
  }

  async getAnomaly(id: string): Promise<Anomaly> {
    return this.fetchJson<Anomaly>(API.anomalies.detail(id));
  }

  async getAnomalyDetail(anomalyId: string): Promise<AnomalyDetail> {
    const [raw, inv] = await Promise.all([
      this.fetchJson<Record<string, unknown>>(API.anomalies.detail(anomalyId)),
      this.fetchJson<Record<string, unknown>>(API.anomalies.investigation(anomalyId)).catch(
        () => null
      ),
    ]);

    const llmHasData =
      raw.context_analysis ||
      raw.pattern_analysis ||
      raw.risk_assessment ||
      raw.recommendations ||
      raw.reasoning_process;

    const llmExplanation: LlmExplanation | null = llmHasData
      ? {
          contextAnalysis: (raw.context_analysis as string) ?? null,
          patternAnalysis: (raw.pattern_analysis as string) ?? null,
          riskAssessment: (raw.risk_assessment as string) ?? null,
          recommendations: (raw.recommendations as string) ?? null,
          reasoningProcess: (raw.reasoning_process as string) ?? null,
          evidenceSummary: (raw.evidence_summary as LlmExplanation['evidenceSummary']) ?? null,
          entitiesReferenced:
            (raw.entities_referenced as LlmExplanation['entitiesReferenced']) ?? null,
          llmSeverityLevel: (raw.llm_severity_level as string) ?? null,
          llmConfidence: raw.llm_confidence != null ? Number(raw.llm_confidence) : null,
          anomalyClassification:
            (raw.anomaly_classification as LlmExplanation['anomalyClassification']) ?? null,
          modelUsed: (raw.model_name as string) ?? null,
          completionTokens: raw.completion_tokens != null ? Number(raw.completion_tokens) : null,
          createdAt: (raw.explanation_created_at as string) ?? null,
        }
      : null;

    let investigation: AnomalyInvestigation | null = null;
    if (inv) {
      const rawFindings = (inv.findings as Record<string, unknown>[]) ?? [];
      const findings: AgentFinding[] = rawFindings.map((f) => ({
        agentType: (f.agent_type as string) ?? '',
        status: (f.status as string) ?? 'pending',
        result: (f.result as Record<string, unknown>) ?? null,
        latencyMs: f.latency_ms != null ? Number(f.latency_ms) : null,
        completedAt: (f.completed_at as string) ?? null,
      }));

      investigation = {
        investigationId: String(inv.investigation_id ?? ''),
        triggeredAt: (inv.triggered_at as string) ?? null,
        completedAt: (inv.completed_at as string) ?? null,
        status: (inv.status as string) ?? 'unknown',
        severityAtTrigger: (inv.severity_at_trigger as string) ?? null,
        agentsInvoked: (inv.agents_invoked as string[]) ?? [],
        confidenceScore: inv.confidence_score != null ? Number(inv.confidence_score) : null,
        overallRecommendation: (inv.overall_recommendation as string) ?? null,
        assignedAnalyst: inv.assigned_analyst
          ? {
              userId: (inv.assigned_analyst as Record<string, unknown>).user_id as string,
              displayName:
                ((inv.assigned_analyst as Record<string, unknown>).display_name as string) ?? '',
              firstName:
                ((inv.assigned_analyst as Record<string, unknown>).first_name as string) ?? null,
              lastName:
                ((inv.assigned_analyst as Record<string, unknown>).last_name as string) ?? null,
              email: ((inv.assigned_analyst as Record<string, unknown>).email as string) ?? '',
              role: ((inv.assigned_analyst as Record<string, unknown>).role as string) ?? '',
              level: ((inv.assigned_analyst as Record<string, unknown>).level as number) ?? null,
              avatarUrl:
                ((inv.assigned_analyst as Record<string, unknown>).avatar_url as string) ?? null,
              avatarInitials:
                ((inv.assigned_analyst as Record<string, unknown>).avatar_initials as string) ??
                null,
              avatarColor:
                ((inv.assigned_analyst as Record<string, unknown>).avatar_color as string) ?? null,
            }
          : null,
        findings,
      };
    }

    return {
      anomalyId: String(raw.anomaly_id ?? ''),
      userId: String(raw.user_id ?? ''),
      user:
        raw.user_display_name != null || raw.user_first_name != null
          ? {
              displayName: (raw.user_display_name as string) ?? null,
              firstName: (raw.user_first_name as string) ?? null,
              lastName: (raw.user_last_name as string) ?? null,
              email: (raw.user_email as string) ?? null,
              jobTitle: (raw.user_job_title as string) ?? null,
              department: (raw.user_department as string) ?? null,
              company: (raw.user_company as string) ?? null,
              seniority: (raw.user_seniority as string) ?? null,
              userRole: (raw.user_role as string) ?? null,
              avatarUrl: (raw.user_avatar_url as string) ?? null,
              avatarInitials: (raw.user_avatar_initials as string) ?? null,
              avatarColor: (raw.user_avatar_color as string) ?? null,
              city: (raw.user_city as string) ?? null,
              country: (raw.user_country as string) ?? null,
            }
          : null,
      timestamp: String(raw.timestamp ?? ''),
      anomalyScore: Number(raw.anomaly_score ?? 0),
      meanAbsZ: raw.mean_abs_z != null ? Number(raw.mean_abs_z) : null,
      severity: (raw.severity as string) ?? null,
      rootCause: (raw.root_cause as string) ?? null,
      subCategory: (raw.sub_category as string) ?? null,
      riskScore: raw.risk_score != null ? Number(raw.risk_score) : null,
      isAnomaly: raw.is_anomaly != null ? Boolean(raw.is_anomaly) : null,
      status: (raw.status as string) ?? null,
      classifiedBy: (raw.classified_by as string) ?? null,
      classificationConfidence:
        raw.classification_confidence != null ? Number(raw.classification_confidence) : null,
      validationConfidence:
        raw.validation_confidence != null ? Number(raw.validation_confidence) : null,
      validationReasoning: (raw.validation_reasoning as string) ?? null,
      dfpRetrainStatus: (raw.dfp_retrain_status as string) ?? null,
      assignedTo: raw.assigned_to != null ? Number(raw.assigned_to) : null,
      analystVerdict: (raw.analyst_verdict as string) ?? null,
      analystNotes: (raw.analyst_notes as string) ?? null,
      reviewedBy: raw.reviewed_by != null ? Number(raw.reviewed_by) : null,
      reviewedAt: (raw.reviewed_at as string) ?? null,
      resolutionNotes: (raw.resolution_notes as string) ?? null,
      resolvedAt: (raw.resolved_at as string) ?? null,
      originalEvent: (raw.original_event as Record<string, unknown>) ?? null,
      rawDetection: (raw.raw_detection as Record<string, unknown>) ?? null,
      aiEnrichment: (raw.ai_enrichment as Record<string, unknown>) ?? null,
      createdAt: (raw.created_at as string) ?? null,
      classifiedAt: (raw.classified_at as string) ?? null,
      validatedBy: (raw.validated_by as string) ?? null,
      processed: Boolean(raw.processed ?? false),
      llmExplanation,
      investigation,
    };
  }

  async reorchestrateAnomaly(
    anomalyId: string
  ): Promise<{ session_id: string; anomaly_id: string }> {
    return this.fetchJson(API.anomalies.reorchestrate(anomalyId), { method: 'POST' });
  }

  async getAnomalyPipeline(
    anomalyId: string
  ): Promise<{ stage: string | null; stages_log: SimProcessEntry[] }> {
    return this.fetchJson(API.anomalies.pipeline(anomalyId));
  }

  async getAnomalyExplanation(anomalyId: string): Promise<AnomalyExplanation> {
    const raw = await this.fetchJson<Record<string, unknown>>(API.anomalies.explanation(anomalyId));
    const shap = raw.shap as Record<string, unknown> | null | undefined;
    const lime = raw.lime as Record<string, unknown> | null | undefined;
    const conf = raw.confidence as Record<string, unknown> | null | undefined;
    return {
      anomalyId: String(raw.anomaly_id ?? ''),
      shap: shap
        ? {
            baseValue: shap.base_value != null ? Number(shap.base_value) : null,
            prediction: shap.prediction != null ? Number(shap.prediction) : null,
            shapUsed: Boolean(shap.shap_used ?? false),
            topDrivers: ((shap.top_drivers as unknown[]) ?? []).map((e: unknown) => {
              const d = e as Record<string, unknown>;
              return {
                feature: String(d.feature ?? ''),
                label: String(d.label ?? ''),
                contribution: Number(d.contribution ?? 0),
                value: Number(d.value ?? 0),
              };
            }),
            topMitigators: ((shap.top_mitigators as unknown[]) ?? []).map((e: unknown) => {
              const m = e as Record<string, unknown>;
              return {
                feature: String(m.feature ?? ''),
                label: String(m.label ?? ''),
                contribution: Number(m.contribution ?? 0),
                value: Number(m.value ?? 0),
              };
            }),
            shapValues: (shap.shap_values as Record<string, number>) ?? {},
          }
        : null,
      lime: lime
        ? {
            limeWeights: ((lime.lime_weights as unknown[]) ?? []).map((e: unknown) => {
              const w = e as Record<string, unknown>;
              return {
                feature: String(w.feature ?? ''),
                label: String(w.label ?? ''),
                weight: Number(w.weight ?? 0),
                value: Number(w.value ?? 0),
              };
            }),
          }
        : null,
      confidence: conf
        ? {
            confidence: Number(conf.confidence ?? 0),
            components: {
              risk: Number((conf.components as Record<string, number>)?.risk ?? 0),
              dfp: Number((conf.components as Record<string, number>)?.dfp ?? 0),
              llm: Number((conf.components as Record<string, number>)?.llm ?? 0),
            },
          }
        : null,
    };
  }

  async updateAnomalyStatus(id: string, status: Anomaly['status']): Promise<Anomaly> {
    return this.fetchJson<Anomaly>(API.anomalies.status(id), {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  }

  // Users
  async getUsers(): Promise<User[]> {
    return this.fetchJson<User[]>(API.users.list);
  }

  async getUser(username: string): Promise<User> {
    return this.fetchJson<User>(API.users.detail(username));
  }

  async getUserProfile(username: string): Promise<UserProfile> {
    return this.fetchJson<UserProfile>(API.users.profile(username));
  }

  // Real-time detections (from Kafka)
  async getRecentDetections(limit = 50): Promise<Detection[]> {
    return this.fetchJson<Detection[]>(API.detections.list(limit));
  }

  // Dashboard dedicated endpoints
  async getDashboardRecentAnomalies(): Promise<DashboardRecentAnomaly[]> {
    return this.fetchJson<DashboardRecentAnomaly[]>(API.dashboard.recentAnomalies);
  }

  async getDashboardRiskDistribution(): Promise<RiskDistribution> {
    return this.fetchJson<RiskDistribution>(API.dashboard.riskDistribution);
  }

  async getDashboardTopUsers(): Promise<TopUser[]> {
    return this.fetchJson<TopUser[]>(API.dashboard.topUsers);
  }

  async getDashboardTopAnomalies(): Promise<TopAnomaly[]> {
    return this.fetchJson<TopAnomaly[]>(API.dashboard.topAnomalies);
  }

  async getDashboardTopRootCauses(): Promise<TopRootCause[]> {
    return this.fetchJson<TopRootCause[]>(API.dashboard.topRootCauses);
  }

  async getDashboardActivityHeatmap(): Promise<HeatmapDay[]> {
    return this.fetchJson<HeatmapDay[]>(API.dashboard.activityHeatmap);
  }

  async getDashboardStatsTrend(): Promise<StatsTrend> {
    return this.fetchJson<StatsTrend>(API.dashboard.statsTrend);
  }

  async getDashboardUserMetrics(): Promise<UserMetrics> {
    return this.fetchJson<UserMetrics>(API.dashboard.userMetrics);
  }

  async getDashboardSystemMaturity(): Promise<SystemMaturity> {
    return this.fetchJson<SystemMaturity>(API.dashboard.systemMaturity);
  }

  async getDashboardPlatformStats(): Promise<PlatformStats> {
    return this.fetchJson<PlatformStats>(API.dashboard.platformStats);
  }

  async getDashboardIntradayRhythm(): Promise<IntradayRhythmCell[]> {
    return this.fetchJson<IntradayRhythmCell[]>(API.dashboard.intradayRhythm);
  }

  async getDashboardInvestigationTrend(): Promise<InvestigationTrendDay[]> {
    return this.fetchJson<InvestigationTrendDay[]>(API.dashboard.investigationTrend);
  }

  // Dashboard consolidated snapshot
  async getDashboardSnapshot(): Promise<DashboardSnapshot> {
    return this.fetchJson<DashboardSnapshot>(API.dashboard.snapshot);
  }

  // Forecast
  async getForecast(periods = 30): Promise<ForecastData> {
    return this.fetchJson<ForecastData>(API.forecast.data(periods));
  }

  async getForecastSummary(): Promise<ForecastSummary> {
    return this.fetchJson<ForecastSummary>(API.forecast.summary);
  }

  async getUserTrend(username: string, days = 30): Promise<UserTrendPoint[]> {
    return this.fetchJson<UserTrendPoint[]>(API.users.trend(username, days));
  }

  async getUserFull(username: string): Promise<UserDetail> {
    return this.fetchJson<UserDetail>(API.users.full(username));
  }

  async getUserAnomalies(
    username: string,
    opts?: {
      page?: number;
      pageSize?: number;
      sortBy?: string;
      sortDir?: string;
      rootCause?: string;
      subCategory?: string;
    }
  ): Promise<PaginatedUserAnomalies> {
    return this.fetchJson<PaginatedUserAnomalies>(API.users.anomalies(username, opts));
  }

  // Stats
  async getStats(): Promise<Stats> {
    return this.fetchJson<Stats>(API.dashboard.stats);
  }

  // Health check
  async healthCheck(): Promise<{ status: string; timestamp: string }> {
    return this.fetchJson(API.health);
  }

  // Anomaly review
  async assignAnomaly(anomalyId: string): Promise<{ status: string; anomaly_id: string }> {
    return this.fetchJson(API.anomalies.assign(anomalyId), { method: 'POST' });
  }

  async reviewAnomaly(
    anomalyId: string,
    verdict: string,
    analystNotes: string,
    resolutionNotes: string
  ): Promise<{ status: string; verdict: string; new_status: string; disagreement: boolean }> {
    return this.fetchJson(API.anomalies.review(anomalyId), {
      method: 'POST',
      body: JSON.stringify({
        verdict,
        analyst_notes: analystNotes,
        resolution_notes: resolutionNotes,
      }),
    });
  }

  // Notifications
  async getNotifications(limit = 50): Promise<AnalystNotification[]> {
    const raw = await this.fetchJson<Record<string, unknown>[]>(
      API.notifications.list + `?limit=${limit}`
    );
    return raw.map((r) => ({
      id: Number(r.id),
      anomalyId: r.anomaly_id != null ? String(r.anomaly_id) : null,
      type: String(r.type ?? ''),
      title: String(r.title ?? ''),
      message: (r.message as string) ?? null,
      seenAt: (r.seen_at as string) ?? null,
      createdAt: (r.created_at as string) ?? null,
    }));
  }

  async getUnreadCount(): Promise<number> {
    const res = await this.fetchJson<{ count: number }>(API.notifications.unreadCount);
    return res.count;
  }

  async markNotificationSeen(notificationId: number): Promise<void> {
    await this.fetchJson(API.notifications.seen(notificationId), { method: 'PATCH' });
  }

  async markAllNotificationsSeen(): Promise<void> {
    await this.fetchJson(API.notifications.seenAll, { method: 'PATCH' });
  }
}

export const api = new ApiService();
