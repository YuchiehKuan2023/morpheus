# AI Modules for Digital Forensics Pipeline

This directory contains AI-powered capabilities that enhance the DFP with advanced threat detection, behavioral analysis, and automated decision-making.

## Module Structure

```text
modules/ai/
├── enrichment/          # Contextual data enrichment
│   ├── geo_enricher.py       # Geolocation enrichment
│   ├── threat_intel.py       # Threat intelligence lookup
│   └── user_profiler.py      # User baseline profiling
│
├── embeddings/          # Vector embeddings for semantic similarity
│   ├── behavior_embedder.py  # Behavioral pattern embeddings
│   └── qdrant_client.py      # Qdrant vector DB integration
│
├── entity_extraction/   # Named Entity Recognition (NER)
│   ├── extractors.py         # Entity extractors (IP, domain, user)
│   └── models.py             # spaCy/transformers models
│
├── clustering/          # Behavioral clustering
│   ├── behavior_clusterer.py # HDBSCAN clustering
│   └── dimensionality.py     # UMAP dimensionality reduction
│
├── root_cause/          # Causal analysis
│   ├── causal_analyzer.py    # Root cause identification
│   └── graph_builder.py      # Event causality graphs
│
├── risk_scoring/        # Dynamic risk assessment
│   ├── risk_scorer.py        # ML-based risk scoring
│   └── threat_models.py      # Threat modeling
│
├── llm/                 # Large Language Model integration
│   ├── gpt_client.py         # GPT-4 integration
│   ├── local_llm.py          # Local LLM (Ollama/LM Studio)
│   └── prompt_templates.py   # Prompt engineering
│
├── forecasting/         # Time-series prediction
│   ├── prophet_forecaster.py # Prophet for anomaly forecasting
│   └── anomaly_detector.py   # Predictive anomaly detection
│
├── agents/              # Autonomous AI agents
│   ├── investigator.py       # Investigation orchestration
│   └── decision_maker.py     # Automated decision agent
│
├── explainability/      # Model interpretability
│   ├── shap_explainer.py     # SHAP values
│   └── lime_explainer.py     # LIME explanations
│
├── feedback/            # Human-in-the-loop
│   ├── feedback_collector.py # Collect analyst feedback
│   └── retraining.py         # Model retraining pipeline
│
├── auto_labeling/       # Automated labeling
│   ├── labeler.py            # Weak supervision labeling
│   └── active_learning.py    # Active learning strategies
│
├── shared/              # Shared utilities
│   ├── config.py             # Configuration management
│   ├── models.py             # Common data models
│   └── utils.py              # Utility functions
│
└── testing/             # Tests
    ├── test_enrichment.py
    ├── test_embeddings.py
    └── ...
```

## Infrastructure

### Vector Database: Qdrant

- **Purpose**: Store and search behavioral embeddings
- **Location**: `data/ai/qdrant/`
- **Port**: 6333
- **Collection**: `user_behaviors`

### Model Tracking: MLflow

- **Purpose**: Track experiments, models, and metrics
- **Location**: `data/ai/mlflow/`
- **Port**: 5000
- **Tracking URI**: `http://localhost:5000`

### Monitoring: Prometheus

- **Purpose**: Real-time metrics and alerting
- **Port**: 9090
- **Metrics**: Model latency, accuracy, throughput

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements-ai.txt
```

### 2. Start Services

```bash
# Qdrant
qdrant --storage-path ./data/ai/qdrant &

# MLflow
mlflow ui --backend-store-uri ./data/ai/mlflow --port 5000 &

# Prometheus
prometheus --config.file=config/prometheus.yml &
```

### 3. Use AI Modules

```python
from modules.ai.enrichment import GeoLocationEnricher
from modules.ai.embeddings import BehaviorEmbedder

# Enrich with geolocation
enricher = GeoLocationEnricher()
enriched_data = enricher.enrich(df)

# Generate embeddings
embedder = BehaviorEmbedder()
embeddings = embedder.embed(user_behaviors)
```

## Integration with DFP Pipeline

AI modules integrate seamlessly with existing Morpheus pipeline:

```python
# In your pipeline
from modules.ai.enrichment import GeoLocationEnricher
from morpheus.stages.preprocess import PreprocessFILStage

# Add AI enrichment stage
pipeline.add_stage(PreprocessFILStage(...))
pipeline.add_stage(GeoLocationEnricher())  # AI enrichment
pipeline.add_stage(DFPTrainingStage(...))
```

## Behavioral Baselines

User baselines defined in `config/user_baselines.yaml`:

- 50 trained users with 70 days of clean data
- Typical apps, locations, browsers, work hours
- Travel patterns and privileged access flags
- Never-accessed applications
- Activity ranges

## Configuration

All AI modules read from:

- `config/user_baselines.yaml` - User behavioral baselines
- `config/mlflow.yaml` - MLflow configuration
- `config/prometheus.yml` - Prometheus metrics config

## Development Guidelines

1. **Module Independence**: Each module should be independently testable
2. **Morpheus Integration**: Use Morpheus stage patterns for pipeline integration
3. **Configuration-Driven**: All models/services configured via YAML
4. **Metrics**: Expose Prometheus metrics for monitoring
5. **Documentation**: Docstrings for all classes and functions
6. **Testing**: Unit tests in `testing/` directory

## Roadmap

- [x] Module structure created
- [ ] Enrichment modules (geo, threat intel, user profiles)
- [ ] Embeddings with Qdrant integration
- [ ] Entity extraction with spaCy
- [ ] Behavioral clustering
- [ ] LLM integration (GPT-4 + local)
- [ ] Root cause analysis
- [ ] Risk scoring models
- [ ] Explainability (SHAP/LIME)
- [ ] Feedback loop and retraining
- [ ] Autonomous agents

## Resources

- [Morpheus Documentation](https://docs.nvidia.com/morpheus/)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [MLflow Documentation](https://mlflow.org/docs/latest/index.html)
- [Sentence-Transformers](https://www.sbert.net/)
- [spaCy NER](https://spacy.io/usage/linguistic-features#named-entities)
