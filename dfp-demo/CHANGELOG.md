# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (Unreleased)

- **Phase E Completeness Audit — Gap Closure** (April 30, 2026)
  - Grafana dashboard: 7 new agentic panels (total queries, avg/max steps, 24h queries, tool distribution pie chart, avg tool latency bar chart)
  - `ClarificationRequest.tsx` — renders `ask_clarification` tool output as clickable option buttons, integrated into `MessageBubble.tsx`
  - `scripts/tests/load_test_chat.sh` — 10-concurrent-session load test with per-query latency tracking, P50/P95/max stats
  - 680 tests passing (no regressions)

- **Phase E Week 30: Hardening, Testing, and Rollout** (April 30, 2026)
  - `test_agent_e2e.py` — 25 end-to-end scenarios covering all 14 tool combinations, multi-turn context, error recovery, planning flows
  - `test_agent_adversarial.py` — 24 adversarial tests: prompt injection (system override, role-play, history injection, tool output injection), malicious parameters (SQL injection, path traversal, oversized input), guard-rail enforcement (blocked tools, budgets, duplicates), infinite loop protection, edge cases (empty/long/unicode/malformed queries)
  - Agentic settings added to `config/base_config.yaml` (models, limits, cache TTLs, streaming toggle)
  - `docs/configuration.rst` updated — agentic chat mode, agent config, guard rails, available tools, API endpoints
  - `docs/architecture.rst` updated — full agent architecture diagram, component listing, data source diagram, observability docs
  - 680 total tests passing (49 new)

- **Phase E Week 29: Frontend + Observability** (April 30, 2026)
  - `TraceStep` dataclass in `agent_core.py` — structured reasoning trace with kind/content/tool/params/success/elapsed_ms
  - `AgentResponse.reasoning_trace` — serialised trace attached to every agent response
  - Trace capture at every ReAct phase: entity resolution, planning, thought, action (with timing), observation, reflection, answer
  - `_serialize_trace()` — JSON-safe serialization with empty-field omission
  - Trace persistence in `chat_messages.data` JSONB column (no new migration needed)
  - `GET /api/v1/chat/agent-metrics` — aggregate stats (total queries, avg/max steps, tool distribution, tool latency)
  - `POST /api/v1/chat/query/stream` — SSE streaming endpoint (step events + answer event)
  - Frontend: `TraceStep`, `AgentMetrics` TypeScript interfaces
  - `ReasoningTrace.tsx` — collapsible "How I found this" panel with step-type icons, tool badges, timing
  - `PlanIndicator.tsx` — plan steps with CheckCircle2 progress indicators
  - `MessageBubble.tsx` — integrated trace + plan components below metadata panel
  - `chatApi.queryStream()` — fetch-based SSE client with event parsing
  - `chatApi.getAgentMetrics()` — typed metrics endpoint client
  - 30 unit tests (631 total passing)

- **Phase E Week 28: Memory System + Conversation Continuity** (April 30, 2026)
  - `chat_memory` table (migration 027) — per-session episodic memory with entity-overlap ranking
  - `EpisodicMemory` — cross-turn persistence: `record_turn()`, `get_relevant_context()`, `get_all_entities()`
  - `EntityTracker` — pronoun resolution ("that user"), ordinal references ("anomaly 1"), email alias auto-creation
  - `extract_entities()` — regex extraction of emails, UUIDs, IPs from free text
  - `AgentCore` integration — `run(session_id=)`, entity resolution before planning, episodic context injection
  - `modules/utils/db.py` — centralized DB connection utility replacing 34 duplicated `os.getenv("POSTGRES_*")` blocks
  - 44 unit tests (172/172 total passing)

- **Phase E Week 27: Advanced RAG Pipeline** (April 30, 2026)
  - PostgreSQL full-text search (migration 026): tsvector + GIN indexes on `enriched_anomalies` and `llm_explanations`
  - `HybridRetriever` — 4-strategy retrieval: dense (Qdrant), sparse (FTS), graph (Neo4j), structured (SQL)
  - `rrf_merge()` — Reciprocal Rank Fusion merger with configurable k parameter
  - `ContextCompressor` — token-budget-aware result formatting (text + dict output)
  - `hybrid_search` tool registered in agent ToolRegistry with fallback to dense-only
  - Centralized `_import_db()` helper for reliable cross-directory db imports
  - 32 unit tests + 9 integration tests (128/128 total passing)

- **Phase E Week 26: Planning + Multi-Step Reasoning** (April 30, 2026)
  - `QueryPlanner` — complexity detection + LLM-generated execution plans for multi-step queries
  - `QueryPlan` / `PlanStep` — ordered plan with dependency tracking and step completion/skipping
  - `needs_planning()` — 20+ keyword heuristics (compare, vs, trend, root cause, correlation, etc.)
  - `Reflector` — standalone self-evaluation module with budget tracking (max 2 reflections/turn)
  - 3 meta-tools: `summarize_results`, `refine_query`, `ask_clarification` via `register_meta_tools()`
  - `PLAN_INJECTION_TEMPLATE` — advisory plan context appended to step prompts
  - Plan-step failure handling — dependent steps automatically skipped on tool failure
  - 44 unit tests + 5 multi-step integration tests (88/88 total passing)

## [0.3.0] - 2025-12-04

### Added ([0.3.0])

- **FilterDetections Integration** (NVIDIA standard binary filtering)
  - Integrated `FilterDetections` module from NVIDIA Morpheus
  - Binary filtering with configurable threshold (mean_abs_z > 2.0)
  - Returns None if no anomalies exceed threshold
  - Comprehensive detection messages with all feature details
    - `features`: Array of all features with {feature, z_score, value}
    - `top_features`: Top 3 features in "feature=value (z=score)" format
    - `timestamp`, `anomaly_score`, `max_abs_z`, `feature_count`

### Changed ([0.3.0])

- **Architecture Simplification**
  - Removed three-layer architecture terminology (Layer 1/2/3)
  - Updated to single DFP pipeline with geographic features
  - travel_speed_kmph now included in AutoEncoder training
  - Models learn normal travel patterns per user (typically 0-100 km/h)
  - FilterDetections provides post-inference binary filtering
- **Documentation Updates**
  - Updated all README.md files to remove layer references
  - Updated ARCHITECTURE.md to reflect single DFP architecture
  - Updated modules/README.md to reflect FilterDetections integration
  - Updated config/README.md to clarify geographic features in training
  - Removed FFT Stage references (not part of current implementation)

### Fixed ([0.3.0])

- **Timestamp Extraction**
  - Fixed missing timestamp in Kafka detection messages
  - Extract timestamp from windowed_df before preprocessing removes it
  - Timestamp now included in ISO format in all detection messages
- **Feature Display Format**
  - Updated top_features format to show actual values + z-scores
  - Changed from "feature=z_score" to "feature=value (z=score)"
  - Example: "travel_speed_kmph=4664.64 (z=4684791.00)"
  - Provides better context for understanding anomalies
- **Test Script Location Data**
  - Added state field to all NOVEL_VALUES locations in test_constants.py
  - Fixed location scenarios in test_novel_event.py to update state field
  - All location changes now consistently update city, state, country
  - Fixed inconsistent location data (Mumbai, Brussels, India → Mumbai, Maharashtra, India)
- **Code Quality**
  - Removed unused variable `last_row_idx` from inference pipeline

## [0.2.0] - 2025-12-01

### Added ([0.2.0])

- **FFT Layer 3 Time-Series Burst Detection** (EPIC-14, 34 story points)
  - Core FFT implementation (`modules/inference/fft_timeseries.py`, 486 lines)
    - `fftAD()` - Fast Fourier Transform anomaly detection with percentile thresholding
    - `zscore()` - Z-score calculation for anomaly scoring
    - `to_periodogram()` - Convert FFT to power spectrum
    - Signal generation functions: `create_event_count_signal()`, `create_location_change_signal()`, `create_velocity_signal()`
    - Automatic CPU/GPU support with NumPy/CuPy fallback
  - FFT pipeline stage (`modules/inference/fft_stage.py`, 322 lines)
    - `FFTTimeSeriesStage` - NVIDIA TimeSeriesStage compliant module
    - ControlMessage processing for per-user FFT analysis
    - Configurable signal types (event_count, location_change, velocity)
    - Integration with inference pipeline
  - Updated `modules/inference/filter_detections.py` for multi-layer filtering
    - Combined detection logic: Geographic | DFP | FFT (OR operation)
    - Source attribution: "geographic", "dfp", "fft", "combined"
    - Multi-layer metadata in detection results
  - FFT configuration in `config/pipeline.yaml`
    - Signal type selection (event_count, location_change, velocity)
    - Configurable window sizes (10s, 1min, 1H)
    - Percentile thresholding (default: 90th percentile)
    - Z-score threshold (default: z > 8)
    - Enable/disable flag (default: false for safe deployment)
- **Comprehensive Test Suite for FFT**
  - Unit tests (`tests/test_modules/test_fft_timeseries.py`, 330 lines, 21 tests)
    - Z-score calculation tests (3 tests)
    - Periodogram generation tests (3 tests)
    - FFT anomaly detection tests (4 tests)
    - Signal generation tests (5 tests)
    - Statistics calculation tests (2 tests)
    - GPU fallback tests (2 tests, skipped on CPU)
    - Full pipeline integration tests (2 tests)
  - Integration tests (`tests/test_fft_integration.py`, 319 lines, 5 tests)
    - Credential spray burst detection test
    - Normal traffic validation (no false positives)
    - Insufficient data handling test
    - Configuration loading validation
    - Stage initialization from production config
  - **Test Results**: 26/26 tests passing (24 passed, 2 skipped GPU tests)
- **Documentation Updates**
  - `docs/implementation/FFT_IMPLEMENTATION_STATUS.md` - Complete implementation status
  - Updated `README.md` with three-layer architecture throughout
  - Updated `modules/README.md` with FFT Layer 3 descriptions
  - Updated `docs/implementation/ARCHITECTURE.md` with multi-layer detection
  - Updated root `README.md` with FFT in Key Features and Key Technologies
- GitHub Actions CI/CD pipeline with multi-platform testing
- Pre-commit hooks for code quality (black, ruff, mypy)
- Dependabot for automated dependency updates
- Security scanning with CodeQL, Bandit, and Safety
- Docker multi-arch support (amd64/arm64)
- Docker Compose for local development environment
- Automated release workflow with changelog generation
- Issue and PR templates
- Apache 2.0 LICENSE
- CODE_OF_CONDUCT.md
- CONTRIBUTING.md with development guidelines
- pyproject.toml with complete package metadata

### Changed ([0.2.0])

- Project structure follows modern Python packaging standards
- Inference pipeline now includes three-layer detection (Geographic → DFP → FFT → Filter)
- Filter detections module updated for multi-layer anomaly attribution
- Documentation updated to reflect complete three-layer architecture
- Version bumped from 0.1.0 to 0.2.0

### Fixed ([0.2.0])

- Integration test metadata keys corrected (`fft_anomalies` → `fft_anomaly_indices`)
- Test configuration adjusted for reliable burst detection (10s window, lower thresholds)
- All 26 FFT tests now passing on CPU with proper NumPy fallback

## [0.1.0] - 2025-11-28

### 2025-11-28 Added

- Three-layer anomaly detection architecture
  - Layer 1: Rule-based velocity filter (> 800 km/h)
  - Layer 2: DFP AutoEncoder behavioral learning
  - Layer 3: FFT time-series burst detection (planned)
- Geographic feature engineering
  - Haversine distance calculation
  - Travel velocity computation
  - Location change tracking
- Training pipeline with user-based model training
- Inference pipeline with real-time anomaly detection
- MLflow integration for model tracking
- Prometheus metrics and Pushgateway integration
- Grafana dashboards for monitoring
- Kafka integration for streaming data
- Comprehensive test suite
- Documentation and implementation guides

[Unreleased]: https://github.com/Deloitte-UK-Innersource/morpheus-dfp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Deloitte-UK-Innersource/morpheus-dfp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Deloitte-UK-Innersource/morpheus-dfp/releases/tag/v0.1.0
