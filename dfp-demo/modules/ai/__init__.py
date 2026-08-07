"""
AI Modules for Digital Forensics Pipeline

This package contains AI-powered components for advanced threat detection,
behavioral analysis, and automated decision-making.

Modules:
    enrichment: Contextual data enrichment (geolocation, threat intel, user profiles)
    embeddings: Vector embeddings for semantic similarity (sentence-transformers)
    entity_extraction: NER for extracting usernames, IPs, domains (spaCy, transformers)
    clustering: Behavioral clustering and pattern discovery (HDBSCAN, UMAP)
    root_cause: Causal analysis and root cause identification
    risk_scoring: Dynamic risk scoring with ML models
    llm: Large Language Model integration (GPT-4, local LLMs)
    forecasting: Time-series prediction and anomaly forecasting (Prophet)
    agents: Autonomous AI agents for investigation orchestration
    explainability: Model interpretability (SHAP, LIME)
    feedback: Human feedback loop and model retraining
    auto_labeling: Automated labeling for continuous learning
    orchestrator: Real-time event router wiring inference pipeline to AI intelligence layer
    shared: Shared utilities, base classes, and configurations
    testing: Unit tests and integration tests for AI modules

Architecture:
- All modules integrate with existing DFP pipeline via Morpheus stages
- Vector storage: Qdrant for embeddings and semantic search
- Model tracking: MLflow for experiment management
- Metrics: Prometheus for real-time monitoring
- Configuration: config/user_baselines.yaml for behavioral baselines

Usage:
    from modules.ai.enrichment import GeoLocationEnricher
    from modules.ai.embeddings import BehaviorEmbedder
    from modules.ai.entity_extraction import EntityExtractor
"""

__version__ = "0.1.0"
__all__ = [
    "enrichment",
    "embeddings",
    "entity_extraction",
    "clustering",
    "root_cause",
    "risk_scoring",
    "llm",
    "forecasting",
    "agents",
    "explainability",
    "feedback",
    "auto_labeling",
    "shared",
    "testing",
]
