import type {
  DashboardLayout,
  DashboardState,
  DashboardStats,
  UsersAnomalyStats,
  SystemMaturity as SystemMaturityData,
  DashboardSection,
  DashboardComponent,
  GraphStats,
  PlatformStats,
} from '@/types';
import {
  Activity,
  Database,
  DatabaseZap,
  FileText,
  FlaskConical,
  Folder,
  Gauge,
  GitMerge,
  Globe,
  Network,
  Scan,
  Server,
  Share2,
  Users,
  Zap,
} from 'lucide-react';

const className = 'no-border no-shadow';
const hero = true;

export const REFRESH_INTERVAL = 60_000; // 60 seconds

export const INVESTIGATION_VIEWS = ['volume', 'rate', 'confidence'] as const;
export const SYSTEM_MATURITY_LEVELS = ['Resilient', 'Managed', 'Developing', 'Exposed'] as const;
export const STAT_TYPES = [
  'totalEvents',
  'totalAnomalies',
  'avgAnomalyScore',
  'totalUsers',
  'activeUsers',
] as const;

export const DASHBOARD_COMPONENTS = [
  'systemMaturity',
  'anomalyActivity',
  'anomalyPattern',
  'investigationThroughput',
  'riskScoreAnalysis',
  'riskDistribution',
  'topRootCauses',
  'anomalyForecast',
  'dfpCoreEngine',
  'aiIntelligenceLayer',
  'multiAgentSystem',
  'graphNetwork',
  'conversationalAi',
  'ragPipeline',
  'dataInfrastructure',
] as const;

export const DASHBOARD_SECTIONS = [
  'anomalyIntelligence',
  'operationalPatterns',
  'riskAndUserAnalysis',
  'trendForecasting',
  'platformArchitecture',
] as const;

export const SECTION_COMPONENT_MAPPING = {
  anomalyIntelligence: ['systemMaturity', 'anomalyActivity'],
  operationalPatterns: ['anomalyPattern', 'investigationThroughput'],
  riskAndUserAnalysis: ['riskScoreAnalysis', 'riskDistribution', 'topRootCauses'],
  trendForecasting: ['anomalyForecast'],
  platformArchitecture: [
    'dfpCoreEngine',
    'aiIntelligenceLayer',
    'multiAgentSystem',
    'graphNetwork',
    'conversationalAi',
    'ragPipeline',
    'dataInfrastructure',
  ],
} as const satisfies Record<DashboardSection, readonly DashboardComponent[]>;

export const DASHBOARD_LAYOUT: DashboardLayout = {
  anomalyIntelligence: {
    section: {
      title: 'Anomaly Intelligence',
      subtitle: 'Organisational security posture and detection activity over time',
    },
    components: {
      systemMaturity: {
        title: 'Overall System Maturity',
        description:
          'An aggregate measure of the system\u2019s security posture based on anomaly distribution and risk levels',
        tooltip:
          'A composite score (0\u2013100) reflecting the organisation\u2019s overall security posture. Computed from the ratio of validated true-positive vs false-positive detections and the severity distribution of confirmed anomalies. Higher scores indicate a well-defended environment where most detections are benign.',
      },
      anomalyActivity: {
        title: 'Anomaly Activity',
        description:
          'Daily detection frequency over the last 17 weeks broken by severity \u2014 darker cells indicate higher activity levels.',
        tooltip:
          'A calendar-style heatmap of daily anomaly detections over the last 17 weeks. Each cell represents one day and is shaded by volume, making it easy to spot spikes, quiet periods, and recurring weekly patterns at a glance.',
      },
    },
  },
  operationalPatterns: {
    section: {
      title: 'Operational Patterns',
      subtitle: 'Temporal rhythms of anomaly detection and investigation response rates',
    },
    components: {
      anomalyPattern: {
        title: 'Hourly Anomaly Pattern',
        description:
          'Each bubble represents the average number of anomalies detected at that hour on that weekday.',
        tooltip:
          'A bubble matrix showing the average number of anomalies detected at each hour of each weekday. Larger bubbles highlight the busiest time slots, helping identify whether anomalous activity clusters around specific working hours or occurs off-hours when legitimate usage is low.',
      },
      investigationThroughput: {
        title: 'Investigation Throughput',
        description: 'Daily triggered vs completed investigations over the last 30 days.',
        tooltip:
          'Tracks daily investigation volume and completion rates. Each anomaly flagged by the AI pipeline triggers an automated investigation \u2014 this chart shows how many were triggered, completed, failed, or remain pending, along with average investigation duration and AI confidence levels.',
      },
    },
  },
  riskAndUserAnalysis: {
    section: {
      title: 'Risk & User Analysis',
      subtitle: 'Highest-risk users, severity distribution, and leading root cause drivers',
    },
    components: {
      riskScoreAnalysis: {
        title: 'Risk Score Analysis',
        description: 'Risk score distribution and statistics',
        tooltip:
          'Summarises the investigation pipeline\u2019s current state: how many anomalies are new, under review, or resolved. Below, fleet-wide gauges show aggregate metrics across all monitored users \u2014 including mean risk score, detection rate, and model confidence \u2014 giving a single-pane view of analyst workload and system effectiveness.',
      },
      riskDistribution: {
        title: 'Risk Distribution',
        description: 'Breakdown by severity band',
        tooltip:
          'Breaks down all validated anomalies by their computed risk score into severity bands (critical, high, medium, low). The risk score combines the anomaly\u2019s statistical deviation, the user\u2019s historical pattern, and contextual factors like location and device to produce a single 0\u2013100 measure of threat likelihood.',
      },
      topRootCauses: {
        title: 'Top Root Causes',
        description: 'Leading drivers of anomaly detections',
        tooltip:
          'Shows the most frequent root cause classifications assigned to anomalies by the DistilBERT classifier. Root causes identify why a detection was flagged \u2014 such as unusual location, novel device, impossible travel, or abnormal application usage \u2014 helping analysts prioritise investigation by attack pattern.',
      },
    },
  },
  trendForecasting: {
    section: {
      title: 'Trend Forecasting',
      subtitle: 'Forward-looking anomaly volume predictions powered by Prophet time-series models',
    },
    components: {
      anomalyForecast: {
        title: 'Anomaly Forecast',
        description:
          'Historical anomaly counts with 30-day Prophet forecast and 90% confidence interval.',
        tooltip:
          'Uses a Facebook Prophet time-series model trained on historical daily anomaly counts to project expected detection volumes over the next 30 days. The shaded band shows the 90% confidence interval. The model retrains automatically through the feedback loop as new anomalies accumulate.',
      },
    },
  },
  platformArchitecture: {
    section: {
      title: 'Platform Architecture',
      subtitle: 'Core components powering the DFP detection and response pipeline',
    },
    components: {
      dfpCoreEngine: {
        title: 'DFP Core Engine',
        description:
          'Real-time anomaly detection pipeline built on NVIDIA Morpheus \u2014 continuously trains on user behaviour, scores live events, and closes the loop with analyst feedback.',
        tooltip:
          'The foundation of the detection platform. NVIDIA Morpheus trains per-user DFP autoencoders on behavioural telemetry, scores incoming events in real time, and continuously improves via a feedback loop that incorporates analyst verdicts into the next training cycle.',
      },
      aiIntelligenceLayer: {
        title: 'AI Intelligence Layer',
        description:
          'AI orchestration layer that labels records, computes composite risk scores, and generates natural-language explanations for every flagged anomaly.',
        tooltip:
          'Orchestrates all AI post-processing after DFP scoring: the heuristic auto-labeler assigns initial verdicts, the DistilBERT classifier predicts root causes, the risk scorer computes composite scores, and the LLM explainer produces human-readable narratives for each detection.',
      },
      multiAgentSystem: {
        title: 'Multi-Agent System',
        description:
          'Autonomous agent network that opens investigations, performs graph-based forensics, and surfaces prioritised remediation actions without human prompting.',
        tooltip:
          'A crew of specialised LLM agents that autonomously investigate flagged anomalies \u2014 the Triage Agent evaluates severity, the Forensics Agent queries the knowledge graph for related activity, and the Response Agent proposes remediation actions, all coordinated by a Supervisor Agent.',
      },
      graphNetwork: {
        title: 'Graph Network',
        description:
          'Neo4j knowledge graph connecting users, devices, applications, and IP addresses \u2014 enabling traversal-based risk scoring across 9 node types and 8 relationship types.',
        tooltip:
          'A Neo4j knowledge graph that models the relationships between users, devices, IP addresses, applications, browsers, operating systems, locations, and anomalies. Agents traverse the graph to discover hidden connections and lateral movement patterns that flat tabular queries would miss.',
      },
      conversationalAi: {
        title: 'Conversational AI',
        description:
          'RAG-powered analyst assistant that answers natural-language queries about users, anomalies, and investigations using GitHub Models inference over a Qdrant vector index.',
        tooltip:
          'An interactive chat interface backed by retrieval-augmented generation. Analysts ask plain-English questions and the assistant retrieves relevant anomaly records, user profiles, and investigation findings from the Qdrant vector store to compose grounded, cited answers.',
      },
      ragPipeline: {
        title: 'RAG Pipeline',
        description:
          'Shared retrieval-augmented generation layer. Supplies enrichment context to the AI Orchestrator and powers semantic search for the Conversational AI assistant.',
        tooltip:
          'Embeds anomaly narratives via MiniLM-L6-v2 into a Qdrant vector index, then retrieves the most relevant documents at query time. This shared layer feeds both the AI Orchestrator (for enrichment) and the Conversational AI (for analyst Q&A).',
      },
      dataInfrastructure: {
        title: 'Data Infrastructure',
        description:
          'Polyglot persistence layer combining relational, graph, vector, and in-memory stores \u2014 each optimised for a distinct workload in the detection and investigation pipeline.',
        tooltip:
          'PostgreSQL stores structured anomaly and user records, Neo4j holds the entity relationship graph, Qdrant indexes vector embeddings for semantic retrieval, Redis provides caching and session management, and MLflow tracks model experiments and artefacts.',
      },
    },
  },
};

export const STATS: DashboardStats = {
  critical: {
    title: 'Critical Risk Anomalies',
    description: 'Anomalies that pose an immediate threat and require urgent attention',
    subtitle: 'Anomalies that pose an immediate threat and require urgent attention',
    variant: 'dark',
    link: '/anomalies?severity=critical',
    hero,
    className,
  },
  high: {
    title: 'High Risk Anomalies',
    description: 'Anomalies that indicate elevated risk and should be investigated promptly',
    subtitle: 'Anomalies that indicate elevated risk and should be investigated promptly',
    link: '/anomalies?severity=high',
    hero,
    className,
  },
  medium: {
    title: 'Medium Risk Anomalies',
    description: 'Anomalies that suggest moderate risk and should be reviewed in a timely manner',
    subtitle: 'Anomalies that suggest moderate risk and should be reviewed in a timely manner',
    link: '/anomalies?severity=medium',
    hero,
    className,
  },
  low: {
    title: 'Low Risk Anomalies',
    description: 'Anomalies that indicate low risk but may warrant attention if patterns emerge',
    subtitle: 'Anomalies that indicate low risk but may warrant attention if patterns emerge',
    link: '/anomalies?severity=low',
    hero,
    className,
  },
  totalEvents: {
    title: 'Total Events Recorded',
    description:
      'Total number of events ingested across all users, including normal and anomalous activity',
    subtitle: 'ingested across all users',
    className,
  },
  totalAnomalies: {
    title: 'Total Anomalies',
    description:
      'Total number of anomalies detected across all users, indicating potential security incidents',
    subtitle: 'across {N} users',
    className,
  },
  avgAnomalyScore: {
    title: 'Average Anomaly Score',
    description:
      'Mean z-score of all detected anomalies, with a threshold of 2.0 indicating potential concern',
    subtitle: 'mean z-score, threshold 2.0',
    className,
  },
  totalUsers: {
    title: 'Users Monitored',
    description:
      'Total number of users with trained profiles, representing the scope of monitoring coverage',
    subtitle: 'total trained profiles',
    variant: 'dark',
    className,
  },
  activeUsers: {
    title: 'Users with Anomalies',
    description:
      'Number of users who have had at least one anomaly detected, indicating potential risk',
    subtitle: 'at least one detection',
    variant: 'dark',
    className,
  },
} as const;

export const USER_ANOMALY_STATS: UsersAnomalyStats = {
  new: {
    title: 'New',
    description: 'Anomalies that have been detected but not yet assigned for investigation',
    subtitle: 'Anomalies not yet assigned',
    className,
  },
  resolved: {
    title: 'Resolved',
    description: 'Anomalies that have been closed and remediated by the security team',
    subtitle: 'Anomalies closed and remediated',
    className,
  },
  pending: {
    title: 'Pending Review',
    description: 'Anomalies assigned to an analyst and awaiting verdict',
    subtitle: 'Assigned, awaiting review',
    className,
  },
};

export const INITIAL_STATE: DashboardState = {
  stats: null,
  statsTrend: null,
  intradayRhythm: [],
  investigationTrend: [],
  recentAnomalies: [],
  riskDistribution: { critical: 0, high: 0, medium: 0, low: 0, total: 0 },
  topAnomalies: [],
  topUsers: [],
  topRootCauses: [],
  activityHeatmap: [],
  userMetrics: null,
  systemMaturity: null,
  loading: true,
};

export const LEVEL_CLASSES: Record<SystemMaturityData['level'], string> = {
  Resilient: 'system-maturity__level--resilient',
  Managed: 'system-maturity__level--managed',
  Developing: 'system-maturity__level--developing',
  Exposed: 'system-maturity__level--exposed',
};

export const LEVEL_SUBTITLES: Record<SystemMaturityData['level'], string> = {
  Resilient:
    'Threats are consistently identified, investigated, and resolved. The security posture is strong — anomaly volumes are well-managed, critical risks are addressed promptly, and resolution rates reflect an effective and responsive detection pipeline.',
  Managed:
    'Most threats are under active investigation and being tracked. While the majority of anomalies are receiving attention, some unresolved cases indicate room for improvement in triage speed or analyst capacity. Resolution workflows are functioning but not yet fully optimised.',
  Developing:
    'Response coverage has notable gaps. A significant portion of anomalies — including high-risk detections — remain unaddressed or in a new state. Processes are in place but inconsistently applied; prioritisation and escalation paths need strengthening to reduce exposure.',
  Exposed:
    'High-risk anomalies are going unaddressed and the security posture is critically weak. A large share of critical and high-severity detections remain new with no active investigation. Immediate attention is required to triage open cases and prevent potential incidents from escalating.',
};

export const BUBBLE_PALETTE = [
  '#a5b4fc', // indigo-300  (User)
  '#fca5a5', // red-300     (Detection)
  '#fcd34d', // amber-300   (Application)
  '#6ee7b7', // emerald-300 (Device)
  '#93c5fd', // blue-300    (Browser)
  '#c4b5fd', // violet-300  (OperatingSystem)
  '#f9a8d4', // pink-300    (IPAddress)
  '#5eead4', // teal-300    (ClientApp)
  '#fdba74', // orange-300  (Location)
  '#d1d5db', // gray-300    (Unknown)
  '#d8b4fe', // purple-300
  '#7dd3fc', // sky-300
  '#86efac', // green-300
  '#fca5a5', // red-300
];

export const getDatabases = ({
  graphStats,
  platformStats,
  qdrantDocs,
  monitoredUsers,
}: {
  graphStats?: GraphStats | null;
  platformStats?: PlatformStats | null;
  qdrantDocs?: string;
  monitoredUsers?: string;
}) =>
  [
    {
      key: 'infra-postgres',
      Icon: Database,
      name: 'PostgreSQL 16 (TimescaleDB)',
      subtitle: 'Primary relational store',
      description:
        'Central relational store holding user profiles, enriched anomalies, agent investigations, and schema migrations.',
      details: [
        {
          Icon: DatabaseZap,
          label: 'High-performance real-time analytics on time-series',
          value: 1,
        },
        {
          Icon: GitMerge,
          label: 'Migrations',
          value: platformStats?.migrationCount != null ? String(platformStats.migrationCount) : '—',
        },
        { Icon: Users, label: 'Monitored users', value: monitoredUsers },
        {
          Icon: Activity,
          label: 'Users w/ anomalies',
          value: platformStats?.usersWithAnomalies?.toLocaleString() ?? '—',
        },
        { Icon: Globe, label: 'Port', value: '5433' },
      ],
    },
    {
      key: 'infra-neo4j',
      Icon: Network,
      name: 'Neo4j 2026.01.4',
      subtitle: 'Knowledge graph',
      description:
        'Graph database mapping users to entities via typed relationships, enabling traversal-based risk scoring.',
      details: [
        { Icon: Server, label: 'Nodes', value: graphStats?.total_nodes?.toLocaleString() ?? '—' },
        {
          Icon: Share2,
          label: 'Relationships',
          value: graphStats?.total_relationships?.toLocaleString() ?? '—',
        },
        { Icon: Globe, label: 'Port', value: '7474 / 7687' },
      ],
    },
    {
      key: 'infra-qdrant',
      Icon: Scan,
      name: 'Qdrant v1.16.3',
      subtitle: 'Vector store · 384-D MiniLM',
      description:
        'High-dimensional vector store powering semantic search across analyst notes and investigation summaries.',
      details: [
        { Icon: FileText, label: 'Documents', value: qdrantDocs },
        {
          Icon: Folder,
          label: 'Collections',
          value:
            platformStats?.qdrantCollections != null
              ? String(platformStats.qdrantCollections)
              : '—',
        },
        { Icon: Globe, label: 'Ports', value: '6333 / 6334' },
      ],
    },
    {
      key: 'infra-redis',
      Icon: Zap,
      name: 'Redis 8.6.0',
      subtitle: 'Embedding & session cache',
      description:
        'In-memory cache layer for embedding vectors and LLM conversation sessions, reducing inference latency.',
      details: [
        { Icon: Activity, label: 'Use', value: 'Embeddings · LLM cache' },
        { Icon: Gauge, label: 'Speed-up', value: '1,944× vs cold' },
        { Icon: Globe, label: 'Port', value: '6379' },
      ],
    },
    {
      key: 'infra-mlflow',
      Icon: FlaskConical,
      name: 'MLflow',
      subtitle: 'Experiment tracking · model registry',
      description:
        'Tracks training runs, hyperparameters, and model versions; serves registered models for production scoring.',
      details: [
        { Icon: Activity, label: 'Experiments', value: 'Auto-logged' },
        { Icon: Folder, label: 'Models', value: 'Versioned artifacts' },
        { Icon: Globe, label: 'Port', value: '5001' },
      ],
    },
  ] as const;
