import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  Database,
  Eye,
  FileSearch,
  GitBranch,
  Layers,
  Lightbulb,
  MessageSquare,
  Network,
  Search,
  Shield,
  Sparkles,
  Target,
  TrendingUp,
  Workflow,
  Zap,
  FlaskConical,
  ScanLine,
  BookOpen,
  Server,
  Users,
  Wrench,
} from 'lucide-react';
import type { Capability } from './types';

// ── DFP Core Engine ──────────────────────────────────────────────────────────
// Morpheus ML inference pipeline: DFP autoencoder training + real-time scoring
export const dfpCoreCapabilities: Capability[] = [
  {
    name: 'User Behavior Modeling',
    description: 'Per-user autoencoder baseline',
    icon: Users,
    color: 'primary',
    models: [
      {
        title: 'DFP Autoencoder',
        description:
          'PyTorch reconstruction-error model. Trained on 70 days of Azure AD telemetry per user.',
        subtitle: 'PyTorch · per-user',
        icon: Brain,
        details: [
          { icon: Layers, label: 'Architecture', value: 'Autoencoder' },
          { icon: Activity, label: 'Training window', value: '70 days' },
        ],
      },
    ],
  },
  {
    name: 'Real-time Inference',
    description: 'NVIDIA Morpheus pipeline',
    icon: Zap,
    color: 'warning',
    models: [
      {
        title: 'Morpheus Pipeline',
        description:
          'GPU-accelerated streaming pipeline. Ingests Azure AD events from Kafka, scores each event against the per-user baseline.',
        subtitle: 'NVIDIA Morpheus',
        icon: Zap,
        details: [
          { icon: Activity, label: 'Source', value: 'Kafka / Azure AD' },
          { icon: Target, label: 'Threshold', value: 'Score > 2.0' },
        ],
      },
    ],
  },
  {
    name: 'Anomaly Scoring',
    description: 'Reconstruction error detection',
    icon: ScanLine,
    color: 'error',
    models: [],
  },
  {
    name: 'Feature Engineering',
    description: '26 Azure AD telemetry features',
    icon: FlaskConical,
    color: 'secondary',
    models: [],
  },
  {
    name: 'Rolling Cache',
    description: 'Per-user inference cache',
    icon: Server,
    color: 'info',
    models: [],
  },
  {
    name: 'MLflow Tracking',
    description: 'Experiment & model registry',
    icon: BookOpen,
    color: 'success',
    models: [
      {
        title: 'MLflow Registry',
        description:
          'Tracks all DFP training runs, model versions, and evaluation metrics. Enables reproducible experiments and model promotion.',
        subtitle: 'MLflow · local',
        icon: BookOpen,
        details: [
          { icon: GitBranch, label: 'Models', value: 'Versioned' },
          { icon: Activity, label: 'Runs', value: 'Auto-logged' },
        ],
      },
    ],
  },
];

// ── AI Intelligence Layer ─────────────────────────────────────────────────────
// AI Orchestrator, auto-labeling (Stage 1 + Stage 2), risk scoring, explainability
export const aiOrchestrationCapabilities: Capability[] = [
  {
    name: 'Stage 1: Anomaly Validation',
    description: 'True / false positive labeling',
    icon: Shield,
    color: 'primary',
    models: [
      {
        title: 'Ensemble Validator',
        description:
          '3-method weighted ensemble: LLM verdict (Meta-Llama-3.1-405B via GitHub Models), similarity, and graph context scoring. Writes is_anomaly + severity to DB.',
        subtitle: 'GitHub Models + Heuristic',
        icon: Shield,
        details: [
          { icon: Layers, label: 'Methods', value: '3-way ensemble' },
          { icon: Target, label: 'Output', value: 'TRUE / FALSE label' },
        ],
      },
    ],
  },
  {
    name: 'Stage 2: Root Cause Classification',
    description: 'DistilBERT · 9-class classifier',
    icon: Brain,
    color: 'secondary',
    models: [
      {
        title: 'DistilBERT Classifier',
        description:
          'Fine-tuned DistilBERT model classifying each anomaly into one of 9 root cause categories (Account Takeover, Credential Compromise, etc.).',
        subtitle: 'DistilBERT · 9 classes',
        icon: Brain,
        details: [
          { icon: Target, label: 'Classes', value: '9 root causes' },
          { icon: Activity, label: 'Framework', value: 'HuggingFace' },
        ],
      },
    ],
  },
  {
    name: 'Risk Scoring',
    description: 'XGBoost multi-factor scorer',
    icon: TrendingUp,
    color: 'warning',
    models: [
      {
        title: 'XGBoost Risk Scorer',
        description:
          'Multi-factor risk score (0-100) combining anomaly score, severity, user history, and root cause. Powers agent dispatch thresholds.',
        subtitle: 'XGBoost',
        icon: TrendingUp,
        details: [
          { icon: Target, label: 'Output range', value: '0 - 100' },
          { icon: Activity, label: 'Dispatch', value: 'All severities' },
        ],
      },
    ],
  },
  {
    name: 'SHAP Explainability',
    description: 'Feature attribution (Shapley)',
    icon: Eye,
    color: 'info',
    models: [
      {
        title: 'SHAP + LIME',
        description:
          'SHAP Shapley values for global feature attribution. LIME local surrogate explanations. Both rendered in the Detection detail UI.',
        subtitle: 'SHAP · LIME',
        icon: Eye,
        details: [
          { icon: Lightbulb, label: 'Global', value: 'SHAP Shapley' },
          { icon: Activity, label: 'Local', value: 'LIME surrogate' },
        ],
      },
    ],
  },
  {
    name: 'AI Orchestrator',
    description: 'Dual Kafka consumer thread',
    icon: Workflow,
    color: 'success',
    models: [
      {
        title: 'AIOrchestrator',
        description:
          'Dual-thread Kafka consumer. Thread 1 processes anomaly events (LLM enrichment via Meta-Llama-3.1-405B + stage 1/2 labeling). Thread 2 consumes clean events. Dispatches agent tasks when risk thresholds are met.',
        subtitle: 'Kafka · dual-thread',
        icon: Workflow,
        details: [
          { icon: Activity, label: 'Topics', value: '2 Kafka topics' },
          { icon: Zap, label: 'Dispatch', value: 'All severities' },
        ],
      },
    ],
  },
  {
    name: 'Batch Labeler',
    description: 'Async background labeling worker',
    icon: Activity,
    color: 'error',
    models: [],
  },
];

// ── Multi-Agent System ────────────────────────────────────────────────────────
// Three autonomous agents: Forensics, Investigation, Remediation
export const multiAgentCapabilities: Capability[] = [
  {
    name: 'Forensics Agent',
    description: 'Attack chain + LLM narrative',
    icon: FileSearch,
    color: 'error',
    models: [
      {
        title: 'ForensicsAgent',
        description:
          'Queries Neo4j to reconstruct the attack chain. Extracts related entities (devices, IPs, apps). Generates a natural-language forensic narrative via Phi-4 (GitHub Models).',
        subtitle: 'Neo4j + GitHub Models',
        icon: FileSearch,
        details: [
          { icon: Network, label: 'Graph', value: 'Neo4j attack chain' },
          { icon: Brain, label: 'Narrative', value: 'Phi-4' },
        ],
      },
    ],
  },
  {
    name: 'Investigation Agent',
    description: 'KNN similarity + recurrence',
    icon: Search,
    color: 'primary',
    models: [
      {
        title: 'InvestigationAgent',
        description:
          'Searches Qdrant for the K nearest historical anomalies using sentence embeddings. Detects recurrence patterns and computes similarity confidence.',
        subtitle: 'Qdrant · MiniLM-L6-v2',
        icon: Search,
        details: [
          { icon: Target, label: 'Search', value: 'KNN k=10' },
          { icon: Activity, label: 'Embeddings', value: 'MiniLM-L6-v2' },
        ],
      },
    ],
  },
  {
    name: 'Remediation Agent',
    description: 'Rule lookup + LLM rationale',
    icon: AlertTriangle,
    color: 'warning',
    models: [
      {
        title: 'RemediationAgent',
        description:
          'Looks up applicable remediation rules from the knowledge base given forensics + investigation context. Generates a prioritised action plan via Phi-4 (GitHub Models).',
        subtitle: 'Rules + GitHub Models',
        icon: AlertTriangle,
        details: [
          { icon: BookOpen, label: 'Rules', value: 'Knowledge base' },
          { icon: Brain, label: 'Plan', value: 'Phi-4' },
        ],
      },
    ],
  },
  {
    name: 'Agent Orchestrator',
    description: 'Investigation lifecycle manager',
    icon: Bot,
    color: 'secondary',
    models: [
      {
        title: 'AgentOrchestrator',
        description:
          'Consumes dfp-agent-tasks Kafka topic. Runs Forensics then Investigation sequentially (rate-limit safe), then Remediation with full context. Persists all findings to PostgreSQL.',
        subtitle: 'Kafka · sequential',
        icon: Bot,
        details: [
          { icon: Workflow, label: 'Execution', value: 'Sequential (1→2→3)' },
          { icon: Database, label: 'Findings', value: 'PostgreSQL' },
        ],
      },
    ],
  },
  {
    name: 'Findings Service',
    description: 'Investigation persistence layer',
    icon: Database,
    color: 'info',
    models: [],
  },
  {
    name: 'Dispatch Policy',
    description: 'Risk-gated agent routing',
    icon: Sparkles,
    color: 'success',
    models: [],
  },
];

// ── Graph Network ─────────────────────────────────────────────────────────────
// Neo4j knowledge graph: 9 node types, 8 relationship types
export const graphCapabilities: Capability[] = [
  {
    name: 'Entity Extraction',
    description: 'spaCy NER + graph population',
    icon: Network,
    color: 'success',
    models: [
      {
        title: 'spaCy NER Service',
        description:
          'Extracts named entities from enriched detections using spaCy en_core_web_sm. Each detection is linked in Neo4j to its Application, Device, IP, Browser, OS, Location and ClientApp nodes.',
        subtitle: 'spaCy en_core_web_sm',
        icon: Network,
        details: [
          { icon: Target, label: 'Entity types', value: '9 node labels' },
          { icon: Activity, label: 'Extractions', value: '9,485+ entities' },
        ],
      },
    ],
  },
  {
    name: 'Knowledge Graph',
    description: 'Neo4j 2026 · 8 rel types',
    icon: GitBranch,
    color: 'primary',
    models: [
      {
        title: 'Neo4j Graph DB',
        description:
          'Stores all users, detections, and their entity connections. Powers ForensicsAgent attack-chain queries and the interactive Graph Explorer page.',
        subtitle: 'Neo4j 2026.01.4',
        icon: GitBranch,
        details: [
          { icon: Layers, label: 'Node labels', value: '9 types' },
          { icon: Activity, label: 'Rel. types', value: '8 types' },
        ],
      },
    ],
  },
  {
    name: 'Dependency Analysis',
    description: 'Cross-entity correlation',
    icon: Workflow,
    color: 'warning',
    models: [],
  },
  {
    name: 'Attack Chain Detection',
    description: 'Temporal path traversal',
    icon: AlertTriangle,
    color: 'error',
    models: [],
  },
  {
    name: 'Graph Explorer',
    description: 'Interactive force-directed UI',
    icon: Eye,
    color: 'info',
    models: [],
  },
];

// ── Conversational AI ─────────────────────────────────────────────────────────
// RAG-powered analyst assistant backed by GitHub Models + Qdrant + PostgreSQL
export const conversationalCapabilities: Capability[] = [
  {
    name: 'Intent Routing',
    description: 'Two-pass GitHub Models chain',
    icon: MessageSquare,
    color: 'secondary',
    models: [
      {
        title: 'gpt-4o-mini + Llama-3.3-70B',
        description:
          'Pass 1: tool selection (5 DFP-specific tools) via gpt-4o-mini router. Pass 2: answer synthesis via Llama-3.3-70B-Instruct. Both served by GitHub Models.',
        subtitle: 'GitHub Models · gpt-4o-mini + Llama-70B',
        icon: Brain,
        details: [
          { icon: Zap, label: 'Latency', value: 'Sub-second' },
          { icon: Activity, label: 'Tools', value: '5 DFP tools' },
        ],
      },
    ],
  },
  {
    name: 'Semantic Search',
    description: 'Qdrant · MiniLM-L6-v2',
    icon: Search,
    color: 'error',
    models: [
      {
        title: 'Vector Similarity Search',
        description:
          'Embeds analyst queries with Sentence-BERT (MiniLM-L6-v2, 384-D). Performs ANN search in Qdrant over the enriched anomaly corpus.',
        subtitle: 'Qdrant · 384-D',
        icon: Search,
        details: [
          { icon: GitBranch, label: 'Dimensions', value: '384-D' },
          { icon: Activity, label: 'Model', value: 'MiniLM-L6-v2' },
        ],
      },
    ],
  },
  {
    name: 'Tool Use',
    description: '14 DFP-specific function-call tools',
    icon: Workflow,
    color: 'primary',
    models: [],
    tools: [
      {
        name: 'Anomaly Search',
        description: 'Filter anomaly records by severity, username, or date range with pagination.',
        source: 'PostgreSQL',
      },
      {
        name: 'Anomaly Detail',
        description:
          'Fetch full details for a single anomaly by UUID, including LLM explanation and SHAP scores.',
        source: 'PostgreSQL',
      },
      {
        name: 'User Profile',
        description:
          "Return a monitored user's complete profile: job title, department, location, risk level.",
        source: 'PostgreSQL',
      },
      {
        name: 'Semantic Search',
        description:
          'Semantic vector search over all anomaly records using Qdrant + all-MiniLM-L6-v2 embeddings.',
        source: 'Qdrant',
      },
      {
        name: 'Risk Summary',
        description:
          'Platform-wide aggregate statistics: anomaly counts by severity and top high-risk users.',
        source: 'PostgreSQL',
      },
      {
        name: 'Top Anomalies',
        description:
          'Individual anomaly records sorted by risk score descending, with pagination support.',
        source: 'PostgreSQL',
      },
      {
        name: 'Investigation Results',
        description:
          'AI multi-agent investigation records: forensics chain, similarity findings, remediation plan.',
        source: 'PostgreSQL',
      },
      {
        name: 'Graph Topology',
        description:
          'Network-topology relationship edges from the Neo4j knowledge graph for a given entity.',
        source: 'Neo4j',
      },
      {
        name: 'Root Cause Summary',
        description:
          'Aggregate statistics grouped by root cause category: counts and average risk scores.',
        source: 'PostgreSQL',
      },
      {
        name: 'LLM Explanations',
        description:
          'LLM-generated analytical explanation records with evidence, risk assessment, and confidence.',
        source: 'PostgreSQL',
      },
      {
        name: 'Behaviour Baseline',
        description:
          'Normal behaviour baseline from monitored_users: typical apps, locations, and login patterns.',
        source: 'PostgreSQL',
      },
      {
        name: 'Anomaly Timeline',
        description:
          'Time-series anomaly counts aggregated by day or week; optionally scoped to one user.',
        source: 'PostgreSQL',
      },
      {
        name: 'Dimension Ranking',
        description:
          'Rank any event dimension (IP, app, location, OS…) by anomaly count or average risk score.',
        source: 'PostgreSQL',
      },
      {
        name: 'Raw SQL Query',
        description:
          'Execute a read-only SELECT query directly against the DFP PostgreSQL database for ad-hoc questions.',
        source: 'PostgreSQL (raw SQL)',
      },
    ],
  },
  {
    name: 'Source Attribution',
    description: 'Traceable responses with citations',
    icon: Shield,
    color: 'warning',
    models: [],
  },
  {
    name: 'Context Awareness',
    description: 'Multi-turn session memory',
    icon: Layers,
    color: 'success',
    models: [],
  },
  {
    name: 'Suggested Queries',
    description: 'Context-aware question hints',
    icon: Lightbulb,
    color: 'info',
    models: [],
  },
];

// ── Analytics Engine (kept for backward compat) ───────────────────────────────
export const analyticsCapabilities: Capability[] = aiOrchestrationCapabilities;

// ── RAG Pipeline ──────────────────────────────────────────────────────────────
// Shared retrieval-augmented generation infrastructure used by AI Orchestrator
// (enrichment context) and Conversational AI (semantic search).
export const ragCapabilities: Capability[] = [
  {
    name: 'Context Assembly',
    description: 'Enrichment context for LLM prompts',
    icon: Layers,
    color: 'primary',
    models: [
      {
        title: 'RAGPipeline',
        description:
          'Assembles structured context from enriched detections before each LLM call: similar historical cases (Qdrant, weight 0.4), Neo4j graph relationships (weight 0.3), and extracted entities (weight 0.2). Capped at 4,000 context tokens.',
        subtitle: 'Qdrant · Neo4j · entities',
        icon: Layers,
        details: [
          { icon: Target, label: 'Similar cases', value: 'weight 0.4' },
          { icon: Network, label: 'Graph context', value: 'weight 0.3' },
          { icon: Activity, label: 'Max tokens', value: '4,000' },
        ],
      },
    ],
  },
  {
    name: 'Vector Retrieval',
    description: 'Qdrant ANN · MiniLM-L6-v2',
    icon: Search,
    color: 'error',
    models: [
      {
        title: 'Qdrant Similarity Search',
        description:
          'Finds the top-K most similar historical anomalies using cosine similarity over 384-D sentence embeddings (MiniLM-L6-v2). Powers both enrichment context injection and the conversational semantic_search_anomalies tool.',
        subtitle: 'Qdrant · 384-D ANN',
        icon: Search,
        details: [
          { icon: GitBranch, label: 'Dimensions', value: '384-D' },
          { icon: Activity, label: 'Embedding model', value: 'MiniLM-L6-v2' },
        ],
      },
    ],
  },
  {
    name: 'Graph Context',
    description: 'Neo4j relationship retrieval',
    icon: Network,
    color: 'secondary',
    models: [],
  },
  {
    name: 'Entity Prioritisation',
    description: 'Ranked entity extraction',
    icon: Target,
    color: 'warning',
    models: [],
  },
  {
    name: 'Anomaly Classification',
    description: 'Rule-based anomaly type labeling',
    icon: ScanLine,
    color: 'info',
    models: [],
  },
  {
    name: 'Cold-start Handling',
    description: 'Graceful fallback for new users',
    icon: Wrench,
    color: 'success',
    models: [],
  },
];

// Stats bar data (static — reflects DFP demo dataset baseline)
export const PLATFORM_STATS = {
  trainedUsers: 17,
  totalDetections: 1978,
  labeledAnomalies: 1000,
  rootCauses: 9,
  qdrantDocuments: 3581,
  qdrantCollections: 1,
} as const;
