# NVIDIA Morpheus DFP Implementation

This repository contains implementations of NVIDIA Morpheus Digital Fingerprinting (DFP) for various use cases.

## Overview

Digital Fingerprinting is an unsupervised machine learning approach for anomaly detection that creates behavioral profiles (fingerprints) for entities like users, devices, or accounts. Using AutoEncoder neural networks, it learns normal patterns and detects deviations that may indicate security threats or anomalous behavior.

## Repository Structure

This repository contains multiple use case implementations demonstrating NVIDIA Morpheus DFP across different domains:

### `dfp-poc/` - Azure AD Authentication Anomaly Detection

The `dfp-poc/` directory contains a **production-ready baseline implementation** of NVIDIA Morpheus DFP for detecting anomalies in Azure AD authentication logs.

**Key Features:**

- NVIDIA 100% compliant modular architecture (`training_pipeline.py` + `inference_pipeline.py`)
- Real-time Kafka streaming inference (10ms poll interval)
- **DFP behavioral learning with geographic features**:
  - AutoEncoder neural networks trained on user behavioral patterns
  - Geographic features (`travel_speed_kmph`) included in behavioral learning
  - Per-user models with generic fallback for new/infrequent users
- **FilterDetections**: NVIDIA standard binary filtering (threshold=2.0, mean_abs_z)
- MLflow model versioning and registry
- Native services (Kafka KRaft, MLflow, Prometheus, Grafana)
- Comprehensive monitoring with 15 predefined alerts
- Behavioral features (logcount, locincrement, appincrement)
- Geographic feature engineering (distance, time, travel velocity)
- Comprehensive detection messages with feature details and z-scores
- Binary anomaly filtering with configurable thresholds

**Use Case**: Azure AD authentication logs
**Detection**: Account takeover, credential stuffing, impossible travel
**Status**: Production-ready baseline — 251/251 tests passing

---

### `dfp-demo/` - Azure AD Anomaly Detection with AI Intelligence Layer

The `dfp-demo/` directory extends the DFP baseline with a full **AI Intelligence Layer** that transforms raw anomaly detections into analyst-ready intelligence, and a **React dashboard** for real-time monitoring.

**Key Features (DFP baseline):**

- Identical NVIDIA-compliant DFP pipeline from the baseline (training + inference)
- Per-user AutoEncoder models with geographic feature learning
- FilterDetections binary filtering (mean_abs_z > 2.0)
- Real-time Kafka streaming, MLflow registry, Prometheus/Grafana monitoring

**AI Intelligence Layer (additional):**

- **AI Orchestrator** — dual-thread consumer processing anomalous and clean events in parallel, separate from the inference loop
- **Enrichment Service** — attaches user profile, device, location context, and historical behaviour summary to every detection
- **Entity Extraction** — spaCy NER extracts users, IPs, systems, and resources; populates a Neo4j knowledge graph
- **Vector Search** — Sentence-BERT embeddings (384-dim) stored in Qdrant; retrieves semantically similar historical detections
- **Root Cause Classification** — DistilBERT 9-class model trained on 1,652 labeled anomalies (Impossible Travel, Unusual Location, Unusual App, Unusual Browser, Unusual OS, Unknown Device, Location+Device, High Logcount, Multi-Factor)
- **Risk Scoring** — XGBoost + SHAP; produces a 0–100 risk score with explainable risk factors stored as JSONB
- **LLM Explanation (RAG)** — GPT-4 / Llama 3 generates a plain-English narrative using detection context + retrieved similar cases as RAG input
- **Auto-Labeling Feedback Loop** — AI-validated true/false positive labels; false positives fed back to DFP retraining pipeline

**AI Infrastructure Services (additional):**

- **PostgreSQL** (port 5432) — full enriched detections, labels, and risk scores (source of truth)
- **Qdrant** (port 6333) — vector database for semantic similarity search
- **Neo4j** (port 7474/7687) — knowledge graph for entity relationships and blast radius
- **Redis** (port 6379) — high-speed cache for AI features and session data

**Frontend Dashboard:**

- React 19 + TypeScript + Vite 7 + Tailwind CSS v4 + shadcn/ui (Nova preset)
- Redux Toolkit for state management, React Router for navigation
- Pages: Dashboard (KPIs, live stats), Anomalies (list, severity filter, AI insights), Users (profiles, risk scores)
- FastAPI backend serving enriched data from PostgreSQL

**Use Case**: Azure AD authentication logs
**Detection**: Account takeover, credential stuffing, impossible travel, privilege escalation
**Status**: AI Intelligence Layer complete — orchestrator test suite currently passing in CI; frontend in active development

---

### `nv-morpheus/` - NVIDIA Morpheus Framework

Contains the official NVIDIA Morpheus framework (branch-25.10) used as the foundation for all DFP implementations.

### Extension to Other Domains

The DFP architecture can be extended to additional use cases by customizing the feature schema:

- **Network Security**: Traffic patterns, protocol usage, connection behavior
- **IoT Security**: Device telemetry, sensor patterns, command sequences
- **Application Security**: API usage, endpoint access, request patterns
- **Financial Services**: Transaction patterns, trading behavior, wire transfer anomalies

---

## Key Technologies

### DFP Core

- **NVIDIA Morpheus DFP**: Digital Fingerprinting modular architecture
- **DFEncoder**: AutoEncoder neural networks for unsupervised anomaly detection
- **FilterDetections**: NVIDIA standard binary anomaly filtering module
- **Apache Kafka**: Real-time streaming (KRaft mode, no Zookeeper)
- **MLflow**: Model versioning and experiment tracking
- **Prometheus + Grafana**: Metrics collection and visualization
- **Python 3.10/3.11**: Runtime environment

### AI Intelligence Layer

- **spaCy**: Named Entity Recognition for user, IP, device, resource extraction
- **Sentence-BERT** (`all-MiniLM-L6-v2`): 384-dimensional semantic embeddings
- **Qdrant**: Vector database for similarity search
- **Neo4j**: Knowledge graph for entity relationships and blast radius analysis
- **DistilBERT**: 9-class fine-tuned root cause classifier
- **XGBoost + SHAP**: Risk scoring with explainable feature contributions
- **GPT-4 / Llama 3**: LLM narrative generation with RAG context
- **PostgreSQL**: Enriched anomaly persistence (source of truth)
- **Redis**: High-speed AI feature cache

### Frontend

- **React 19 + TypeScript**: UI components and type safety
- **Vite 7**: Build tool and development server
- **Tailwind CSS v4**: Utility-first styling
- **shadcn/ui (Nova preset)**: Component library built on Radix UI
- **Redux Toolkit**: Application state management
- **FastAPI**: Backend REST API serving enriched data

---

## Documentation

- [DFP-Demo README](./dfp-demo/README.md) — Full implementation guide including AI layer and frontend
- [DFP-PoC README](./dfp-poc/README.md) — Baseline DFP implementation guide
- [AI Intelligence Layer](./dfp-demo/docs/implementation/AI_INTELLIGENCE_LAYER.md) — Architecture reference
- [AI Orchestrator](./dfp-demo/docs/implementation/AI_ORCHESTRATOR.md) — Orchestrator design
- [Progress Tracker](./dfp-demo/docs/implementation/PROGRESS_TRACKER.md) — Implementation status

## References

- [NVIDIA Morpheus Documentation](https://docs.nvidia.com/morpheus/)
- [Digital Fingerprinting Guide](https://docs.nvidia.com/morpheus/developer_guide/guides/5_digital_fingerprinting.html)
- [NVIDIA Morpheus GitHub](https://github.com/nv-morpheus/Morpheus)

## License

See individual implementation directories for licensing information.
