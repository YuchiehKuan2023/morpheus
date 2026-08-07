#!/usr/bin/env python3
"""
Anomaly Validator: Multi-Method Ensemble for False Positive Detection

Uses 3 validation methods to determine if a detection is a TRUE anomaly
or FALSE positive:
    1. LLM Analysis (weight: 0.50) - Semantic reasoning with full context
    2. Similarity Check (weight: 0.30) - Learn from similar labeled cases
    3. Graph Context (weight: 0.20) - Historical patterns and peer comparison

Ensemble voting combines all methods with weighted confidence scoring.
NO RULE-BASED METHODS - Pure data-driven approach to avoid bias.

Architecture:
    Input: enriched_detection (from PostgreSQL)
    Processing:
        1. Each method votes: true/false + confidence
        2. Weighted ensemble combines votes
        3. Final decision based on threshold (0.5)
    Output: ValidationResult with is_anomaly, confidence, reasoning

Usage:
    >>> validator = AnomalyValidator()
    >>> result = validator.validate(enriched_detection)
    >>> print(f"Is Anomaly: {result['is_anomaly']} (confidence: {result['confidence']})")

Reference:
    docs/implementation/LABELING_FEEDBACK_ARCHITECTURE.md
    docs/implementation/PROGRESS_TRACKER.md (Week 9-10: Auto-Labeling)

Author: AI Intelligence Layer Team
Date: 2026-02-27
"""

import json
import logging
import os
from pathlib import Path

# Load .env from project root (3 levels up from this file).
# Must happen before any os.getenv() calls, including lazy service imports.
try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).parents[3] / ".env"
    load_dotenv(_env_path, override=False)  # override=False: real env vars take precedence
    if _env_path.exists():
        logging.getLogger(__name__).debug(f"Loaded .env from {_env_path}")
except ImportError:
    pass  # python-dotenv not installed; rely on env vars being set externally

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class AnomalyValidator:
    """
    Multi-method ensemble validator for anomaly/false-positive classification.

    Combines 5 validation methods with weighted voting to determine if a
    detection is a true anomaly or false positive.
    """

    # Ensemble weights (sum to 1.0) - NO RULE-BASED METHODS
    WEIGHTS = {
        "llm": 0.50,  # LLM semantic analysis (highest weight)
        "similarity": 0.30,  # Similar labeled cases (data-driven)
        "graph": 0.20,  # Graph context (historical patterns)
    }

    # Decision threshold — deliberately higher than the naive 0.5 midpoint.
    # Rationale: the ensemble normalises by active-method weights, meaning a lone
    # LLM vote with 51 % confidence would otherwise decide the outcome.  0.65 requires
    # either (a) high LLM confidence (> 0.65) or (b) meaningful multi-method agreement.
    # 0.75 was considered but rejected: it would suppress genuine threats when the
    # Graph method is sparse (Neo4j not fully populated) — producing false negatives.
    ANOMALY_THRESHOLD = 0.65  # Score ≥ 0.65 → TRUE anomaly

    def __init__(self, config_path: str | None = None):
        """
        Initialize anomaly validator with configuration.

        Args:
            config_path: Path to configuration file (optional)
        """
        self.config = self._load_config(config_path)

        # Lazy-load services (only initialize when needed)
        self._llm_service = None
        self._similarity_service = None
        self._graph_service = None

        logger.info("AnomalyValidator initialized")
        logger.info(f"   Weights: {self.WEIGHTS}")
        logger.info(f"   Threshold: {self.ANOMALY_THRESHOLD}")

    def _load_config(self, config_path: str | None = None) -> dict:
        """Load configuration from file or use defaults."""
        if config_path and Path(config_path).exists():
            import yaml

            with open(config_path) as f:
                return yaml.safe_load(f)

        # Default configuration
        return {
            "llm_validation_enabled": True,
            "similarity_top_k": 5,  # Top 5 most similar cases
            "similarity_threshold": 0.75,  # Similarity score threshold
            "min_confidence": 0.4,  # Below this → flag for review
            "high_confidence": 0.7,  # Above this → high trust
        }

    @property
    def llm_service(self):
        """Lazy-load LLM service."""
        if self._llm_service is None:
            from modules.ai.llm.llm_service import LLMService

            # Uses LLM_ORCHESTRATOR_MODEL so validator and enrichment share the
            # same model/quota bucket (both are AI Orchestrator responsibilities).
            self._llm_service = LLMService(model_name=os.getenv("LLM_ORCHESTRATOR_MODEL"))
        return self._llm_service

    @property
    def similarity_service(self):
        """Lazy-load similarity search service."""
        if self._similarity_service is None:
            from modules.ai.embeddings.similarity_search import SimilaritySearch

            self._similarity_service = SimilaritySearch()
        return self._similarity_service

    @property
    def graph_service(self):
        """Lazy-load graph service for historical queries."""
        if self._graph_service is None:
            from neo4j import GraphDatabase

            neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            neo4j_user = os.getenv("NEO4J_USER", "neo4j")
            neo4j_password = os.getenv("NEO4J_PASSWORD", "")
            self._graph_service = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        return self._graph_service

    def validate(
        self,
        enriched_detection: dict,
        llm_explanation: dict | None = None,
        db_conn=None,
    ) -> dict:
        """
        Validate if detection is TRUE anomaly or FALSE positive.

        Args:
            enriched_detection: Full enriched detection from PostgreSQL
                Must contain: user_id, raw_detection, ai_enrichment, original_event
            llm_explanation: Optional row from llm_explanations table for this detection.
                Only factual/observational fields are used (context_analysis,
                pattern_analysis, evidence_summary, entities_referenced,
                user_baseline_used, reasoning_process).
                Verdict fields (anomaly_classification, severity_level,
                confidence_score, risk_assessment) are intentionally excluded
                to prevent confirmation bias from a peer model.
            db_conn: Optional live psycopg2 connection used by _similarity_check() to
                look up current is_anomaly labels on similar cases. Without this,
                Similarity method always abstains (the ai_enrichment snapshot never
                carries labels — labeling happens after enrichment).

        Returns:
            {
                "is_anomaly": true/false/None  (None = UNCERTAIN — pending human review),
                "confidence": 0.0-1.0,
                "reasoning": "Combined analysis",
                "method": "ensemble",
                "votes": {
                    "llm": {"vote": true, "confidence": 0.85, "reasoning": "..."},
                    "similarity": {"vote": false, "confidence": 0.60, "reasoning": "..."},
                    "graph": {"vote": true, "confidence": 0.75, "reasoning": "..."}
                },
                "weighted_score": 0.68
            }
        """
        logger.info(f"Validating detection: {enriched_detection.get('anomaly_id', 'N/A')}")

        # Collect votes from all methods (3-method ensemble, no rule-based bias)
        votes = {}

        # Method 1: LLM Analysis
        votes["llm"] = self._llm_analysis(enriched_detection, llm_explanation)

        # Method 2: Similarity Check (learn from labeled cases)
        votes["similarity"] = self._similarity_check(enriched_detection, db_conn=db_conn)

        # Method 3: Graph Context (historical patterns)
        votes["graph"] = self._graph_context(enriched_detection)

        # Ensemble voting
        result = self._ensemble_vote(votes)

        logger.info(
            f"   Result: is_anomaly={result['is_anomaly']} "
            f"(confidence={result['confidence']:.2f}, "
            f"score={result['weighted_score']:.2f}, normalized={result['normalized_score']:.2f})"
        )

        return result

    def _llm_analysis(self, enriched_detection: dict, llm_explanation: dict | None = None) -> dict:
        """
        Method 1: LLM Analysis (weight: 0.50)

        Uses LLM to analyze detection context and determine if truly anomalous.
        Highest weight due to semantic understanding and reasoning capability.

        Args:
            enriched_detection: Full detection with enrichment context
            llm_explanation: Optional prior analysis from llm_explanations table

        Returns:
            {
                "vote": true/false,
                "confidence": 0.0-1.0,
                "reasoning": "LLM explanation"
            }
        """
        if not self.config.get("llm_validation_enabled", True):
            logger.info("   Method 1 (LLM): Disabled")
            # confidence=0.0 so this method abstains from ensemble rather than nudging a direction
            return {"vote": False, "confidence": 0.0, "reasoning": "LLM validation disabled — method abstains"}

        logger.info("   Method 1 (LLM): Analyzing...")

        try:
            # Build validation prompt
            prompt = self._build_validation_prompt(enriched_detection, llm_explanation)

            # Delegate provider/client resolution to LLMService — it already reads
            # llm.yaml once at init and stores the resolved provider + client.
            svc = self.llm_service
            provider = svc.provider
            client = svc.client

            if provider == "ollama":
                model_to_use = svc.main_model
                # Ollama's OpenAI-compatible endpoint does not reliably honour
                # response_format={"type": "json_object"} for all models/versions.
                # We rely on parse_llm_json to extract JSON from free-form output instead.
                use_json_mode = False
                logger.info(f"   Method 1 (LLM): Using Ollama ({model_to_use})")
            else:
                model_to_use = svc.main_model
                use_json_mode = True  # GitHub Models and Groq both support response_format natively

            # Build call kwargs — only add response_format when the provider supports it
            call_kwargs: dict = {
                "model": model_to_use,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a cybersecurity analyst validating anomaly detections. "
                            "Determine if the flagged behaviour is a TRUE ANOMALY, a FALSE POSITIVE, or UNCERTAIN. "
                            "Use UNCERTAIN when the evidence does not clearly favour either interpretation. "
                            "UNCERTAIN events will be escalated for human review — do not force a binary decision when the evidence is ambiguous. "
                            'Respond with JSON: {"verdict": "TRUE_ANOMALY"|"FALSE_POSITIVE"|"UNCERTAIN", "confidence": 0-1, "reasoning": "..."}. '
                            "Be evidence-driven: base your decision solely on the data provided. "
                            "Important: TRUE_ANOMALY confidence should reflect how certain YOU are, not how severe the z-scores are. "
                            "Low anomaly scores (2.0-2.5) combined with a single-feature deviation and no authentication failure "
                            "are rarely TRUE ANOMALY — treat them as FALSE POSITIVE or UNCERTAIN unless the full context compels otherwise."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": float(os.getenv("LLM_TEMPERATURE", "0.3")),
                # Override via LLM_MAX_TOKENS env var if needed.
                "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "3800")),
            }
            if use_json_mode:
                call_kwargs["response_format"] = {"type": "json_object"}

            response = client.chat.completions.create(**call_kwargs)

            # Parse response — use shared json_parser for resilient handling of edge cases
            from modules.ai.shared.json_parser import parse_llm_json

            result_text = response.choices[0].message.content
            if not result_text:
                raise ValueError("LLM returned empty response")
            result = parse_llm_json(
                result_text,
                fallback_structure={"verdict": None, "confidence": 0.0, "reasoning": "JSON parse failed"},
            )

            # Support both new schema {verdict: ...} and legacy {is_anomaly: ...}
            verdict_raw = result.get("verdict")
            if verdict_raw is None:
                # Legacy fallback
                legacy = result.get("is_anomaly")
                if legacy is None:
                    return {"vote": False, "confidence": 0.0, "reasoning": "JSON parse failed — method abstains"}
                verdict_raw = "TRUE_ANOMALY" if legacy else "FALSE_POSITIVE"

            verdict_upper = str(verdict_raw).upper().replace(" ", "_")
            if verdict_upper == "UNCERTAIN":
                # Ambiguous signal — LLM abstains from ensemble
                logger.info("      LLM verdict: UNCERTAIN — method abstains")
                return {
                    "vote": False,
                    "confidence": 0.0,
                    "reasoning": f"UNCERTAIN — method abstains: {result.get('reasoning', 'no detail')}",
                }

            vote = verdict_upper == "TRUE_ANOMALY"
            confidence = float(result.get("confidence", 0.5))
            reasoning = result.get("reasoning", "No reasoning provided")

            logger.info(f"      LLM verdict: {vote} (confidence: {confidence:.2f})")

            return {"vote": vote, "confidence": confidence, "reasoning": reasoning}

        except Exception as e:
            err_str = str(e)
            # 429 rate-limit: don't block the pipeline waiting 60s — just abstain.
            if "429" in err_str or "rate_limit" in err_str.lower() or "too many requests" in err_str.lower():
                logger.warning("   Method 1 (LLM): Rate-limited — abstaining (not waiting)")
                return {"vote": False, "confidence": 0.0, "reasoning": "Rate limited — method abstains"}
            logger.warning(f"   Method 1 (LLM): Error - {e}")
            # confidence=0.0: method abstains — error is not evidence either way
            return {"vote": False, "confidence": 0.0, "reasoning": f"LLM validation failed — method abstains: {str(e)}"}

    def _build_validation_prompt(self, enriched_detection: dict, llm_explanation: dict | None = None) -> str:
        """
        Build comprehensive LLM validation prompt with FULL context.

        Includes:
        - Complete original_event (risk levels, auth, device, location)
        - Full user_baseline (work patterns, typical behavior, role)
        - AI enrichment (similar cases WITH labels, graph insights)
        - Feature values (actual vs baseline, not just z-scores)
        - Prior analysis from llm_explanations (factual fields only — no verdicts,
          no severity labels, no confidence scores, to avoid confirmation bias)

        Args:
            enriched_detection: Full detection with all context
            llm_explanation: Optional row from llm_explanations (factual fields only)

        Returns:
            Rich validation prompt with complete context
        """
        user_id = enriched_detection.get("user_id", "unknown")
        raw_detection = enriched_detection.get("raw_detection", {})
        ai_enrichment = enriched_detection.get("ai_enrichment", {})
        original_event = enriched_detection.get("original_event", {})

        # ===== DETECTION METADATA =====
        # mean_abs_z is a top-level DB column AND may exist inside raw_detection JSONB;
        # try JSONB first, fall back to the top-level column, then anomaly_score column.
        anomaly_score = (
            raw_detection.get("mean_abs_z")
            or enriched_detection.get("mean_abs_z")
            or enriched_detection.get("anomaly_score")
            or 0.0
        )
        timestamp = enriched_detection.get("timestamp", "unknown")

        # DFP detection threshold (NVIDIA standard, from config/pipeline.yaml)
        # Every detection in this database already passed this threshold.
        # Severity interpretation is intentionally left to the LLM to avoid confirmation bias.
        DETECTION_THRESHOLD = 2.0
        score_above_threshold = anomaly_score - DETECTION_THRESHOLD

        # ===== ORIGINAL EVENT CONTEXT =====
        # Extract rich context from Azure AD SignInLog
        properties = original_event.get("properties", {})
        device_detail = properties.get("deviceDetail", {})
        location = original_event.get("location", {})

        # Application
        app = properties.get("appDisplayName", "Unknown")

        # Risk indicators
        risk_state = properties.get("riskState", "none")
        risk_level = properties.get("riskLevelAggregated", "none")
        risk_detail = properties.get("riskDetail", "none")

        # Authentication
        auth_requirement = properties.get("authenticationRequirement", "unknown")
        auth_methods = properties.get("authenticationMethodsUsed", [])

        # Device details
        device_name = device_detail.get("displayName", "Unknown")
        browser = device_detail.get("browser", "Unknown")
        os = device_detail.get("operatingSystem", "Unknown")
        device_trust = device_detail.get("isCompliant", "unknown")
        device_managed = device_detail.get("isManaged", "unknown")

        # Location details
        city = location.get("city", "Unknown")
        country = location.get("countryOrRegion", "Unknown")
        coordinates = location.get("geoCoordinates", {})
        latitude = coordinates.get("latitude", "N/A")
        longitude = coordinates.get("longitude", "N/A")

        # Network — ipAddress is at root level in SignInLog but may be in properties too
        ip_address = original_event.get("ipAddress") or properties.get("ipAddress") or "Unknown"

        # ===== DFP FEATURES WITH VALUES =====
        features_str = self._format_features_with_values(raw_detection.get("parsed_features", {}))

        # ===== USER BASELINE (COMPLETE) =====
        # Profile structure: {"apps": {"count": N, "most_common": [["name", count], ...], "all": [...]}, ...}
        user_baseline = ai_enrichment.get("user_baseline", {})
        baseline_available = user_baseline.get("baseline_available", True)

        def _most_common_names(field: str, top: int = 10) -> list[str]:
            """Extract names from most_common list of [name, count] pairs."""
            entries = user_baseline.get(field, {}).get("most_common", [])
            return [e[0] for e in entries[:top] if isinstance(e, (list, tuple)) and len(e) >= 1]

        typical_apps = _most_common_names("apps")
        typical_locations = _most_common_names("locations", 5)
        typical_devices = _most_common_names("devices", 5)
        typical_browsers = _most_common_names("browsers", 5)
        typical_os = _most_common_names("operating_systems", 5)

        # Counts for context
        app_count = user_baseline.get("apps", {}).get("count", 0)
        location_count = user_baseline.get("locations", {}).get("count", 0)
        device_count = user_baseline.get("devices", {}).get("count", 0)

        total_training_events = user_baseline.get("total_events", "Unknown")
        baseline_strength = user_baseline.get("baseline_strength", "Unknown")
        first_seen = user_baseline.get("first_event", "Unknown")
        last_seen = user_baseline.get("last_event", "Unknown")
        baseline_status = "No — no training profile for this user" if not baseline_available else "Yes"

        # ===== SIMILAR CASES WITH LABELS =====
        similar_detections = ai_enrichment.get("similar_detections", [])
        similar_summary = self._format_similar_cases(similar_detections)

        # ===== GRAPH INSIGHTS =====
        graph_context = ai_enrichment.get("graph_context", {})
        graph_summary = self._format_graph_insights(graph_context)

        # ===== PRIOR ANALYSIS (factual observations only, no verdicts) =====
        prior_analysis_summary = self._format_prior_analysis(llm_explanation)

        # ===== BUILD COMPREHENSIVE PROMPT =====
        prompt = f"""
Validate this anomaly detection with FULL context:

═══════════════════════════════════════════════════════════════════
DETECTION METADATA
═══════════════════════════════════════════════════════════════════
User: {user_id}
Timestamp: {timestamp}
Anomaly Score: {anomaly_score:.2f} (DFP mean absolute z-score across all features)
Detection Threshold: {DETECTION_THRESHOLD:.1f} (NVIDIA standard — every record here already exceeded this)
Score Above Threshold: +{score_above_threshold:.2f} (raw distance above detection threshold)

═══════════════════════════════════════════════════════════════════
DETECTED BEHAVIOR (from original Azure AD event)
═══════════════════════════════════════════════════════════════════
Application: {app}
Location: {city}, {country} (lat: {latitude}, lon: {longitude})
IP Address: {ip_address}

Device:
- Name: {device_name}
- Browser: {browser}
- OS: {os}
- Compliant: {device_trust}
- Managed: {device_managed}

Authentication:
- Requirement: {auth_requirement}
- Methods: {", ".join(auth_methods) if auth_methods else "None"}

Risk Indicators:
- Risk State: {risk_state}
- Risk Level: {risk_level}
- Risk Detail: {risk_detail}

═══════════════════════════════════════════════════════════════════
DFP FEATURES (Actual Values vs Statistical Anomaly)
═══════════════════════════════════════════════════════════════════
{features_str}

═══════════════════════════════════════════════════════════════════
USER BASELINE BEHAVIOR
═══════════════════════════════════════════════════════════════════
Baseline available: {baseline_status}
Training events: {total_training_events}
Baseline strength: {baseline_strength}
Profile period: {first_seen} → {last_seen}

Typical Apps ({app_count} distinct): {", ".join(typical_apps) if typical_apps else "None"}
Typical Locations ({location_count} distinct): {", ".join(typical_locations) if typical_locations else "None"}
Typical Devices ({device_count} distinct): {", ".join(typical_devices) if typical_devices else "None"}
Typical Browsers: {", ".join(typical_browsers) if typical_browsers else "None"}
Typical OS: {", ".join(typical_os) if typical_os else "None"}

═══════════════════════════════════════════════════════════════════
SIMILAR CASES (Learn from history)
═══════════════════════════════════════════════════════════════════
{similar_summary}

═══════════════════════════════════════════════════════════════════
GRAPH CONTEXT (Historical patterns)
═══════════════════════════════════════════════════════════════════
{graph_summary}

═══════════════════════════════════════════════════════════════════
PRIOR ANALYSIS CONTEXT
(Factual observations from a separate analysis pass — no verdict included)
═══════════════════════════════════════════════════════════════════
{prior_analysis_summary}

═══════════════════════════════════════════════════════════════════
VALIDATION TASK
═══════════════════════════════════════════════════════════════════
Based on ALL the context above, determine if this detection is:

1. TRUE_ANOMALY: Genuinely suspicious behaviour warranting investigation
   - Strong deviation from user baseline with no benign explanation
   - Risk indicators or authentication failures present
   - Unusual for this user's role and context
   - Context supports a plausible security threat

2. FALSE_POSITIVE: Legitimate unusual activity (not malicious)
   - Explainable by business context (travel, new device adoption, workflow change)
   - Similar to past false positives in labeled history
   - No risk indicators; consistent with user role despite statistical anomaly
   - Low anomaly score (2.0–2.5) with single-feature deviation only

3. UNCERTAIN: Evidence does not clearly favour either interpretation
   - Mixed signals across methods or methods abstained
   - Low confidence even after full analysis
   - Human review recommended before taking action
   USE THIS when you are not confident. Forcing a binary decision on ambiguous
   evidence is worse than abstaining.

IMPORTANT — Avoid over-classifying as TRUE_ANOMALY:
- An anomaly score of 2.0–2.5 (LOW severity) represents a small statistical deviation.
  It should NOT default to TRUE_ANOMALY unless there are clear supporting risk signals.
- A single novel OS, browser, or application alone — with no authentication failure,
  no impossible travel, and a known device — is rarely sufficient evidence for TRUE_ANOMALY.
- Use the similar case labels as a signal but not a vote: if all prior similar cases are
  labeled TRUE_ANOMALY without strong evidence, treat that as potential label noise.

Respond with JSON: {{"verdict": "TRUE_ANOMALY"|"FALSE_POSITIVE"|"UNCERTAIN", "confidence": 0.0-1.0, "reasoning": "detailed explanation"}}

Be data-driven: Use the provided context, not hardcoded rules. Consider similar case labels and graph patterns.
""".strip()

        return prompt

    def _format_features_with_values(self, features: dict) -> str:
        """Format features with actual values AND z-scores."""
        if not features:
            return "No feature details available"

        lines = []
        for feature, data in features.items():
            if isinstance(data, dict):
                value = data.get("value", "N/A")
                zscore = data.get("zscore", 0.0)
                lines.append(f"- {feature}: {value} (z-score: {zscore:.2f})")
            else:
                lines.append(f"- {feature}: {data}")

        return "\n".join(lines) if lines else "No feature data"

    def _format_similar_cases(self, similar_detections: list) -> str:
        """Format similar cases with their labels if available."""
        if not similar_detections:
            return "No similar cases found in database"

        lines = [f"Found {len(similar_detections)} similar cases:"]
        for i, case in enumerate(similar_detections[:5], 1):  # Top 5
            similarity = case.get("similarity_score", 0.0)
            is_anomaly = case.get("is_anomaly", "unlabeled")

            if is_anomaly == "unlabeled" or is_anomaly is None:
                label = "(unlabeled)"
            elif is_anomaly:
                label = "(TRUE ANOMALY)"
            else:
                label = "(FALSE POSITIVE)"

            lines.append(f"{i}. Similarity: {similarity:.2f} {label}")

        return "\n".join(lines)

    def _format_prior_analysis(self, llm_explanation: dict | None) -> str:
        """
        Format prior analysis from llm_explanations using ONLY factual/observational fields.

        Intentionally EXCLUDED to prevent confirmation bias from a peer model:
        - anomaly_classification  (verdict)
        - severity_level          (pre-labeled severity)
        - confidence_score        (anchors our confidence)
        - risk_assessment         (contains security conclusions)
        - recommendations         (action-oriented, implies a verdict)
        - human_feedback          (ground truth — would trivially anchor the LLM)
        - reasoning_process       (EXCLUDED: always contains the prior model’s verdict in
                                   narrative form, e.g. “I classified this as account takeover”.
                                   Including it creates direct confirmation bias.)
        """
        if not llm_explanation:
            return "No prior analysis available"

        lines = []

        # Factual: what was observed (no verdict)
        context = llm_explanation.get("context_analysis")
        if context:
            lines.append(f"Context Observation:\n{context}")

        pattern = llm_explanation.get("pattern_analysis")
        if pattern:
            lines.append(f"\nBehavioral Pattern Observed:\n{pattern}")

        evidence = llm_explanation.get("evidence_summary")
        if evidence:
            # evidence_summary is JSONB in migration 004 — handle both str and dict
            if isinstance(evidence, dict):
                evidence = json.dumps(evidence, indent=2)
            lines.append(f"\nKey Evidence Noted:\n{evidence}")

        # Entities involved (factual graph)
        entities = llm_explanation.get("entities_referenced")
        if entities:
            if isinstance(entities, dict):
                entities = json.dumps(entities)
            lines.append(f"\nEntities Referenced: {entities}")

        # Training baseline used by the prior analysis (may differ from ai_enrichment profile)
        baseline = llm_explanation.get("user_baseline_used")
        if baseline:
            if isinstance(baseline, dict):
                total = baseline.get("total_events", "?")
                strength = baseline.get("baseline_strength", "?")
                top_apps = baseline.get("top_apps", [])
                top_locs = baseline.get("top_locations", [])
                lines.append(
                    f"\nTraining Baseline Used: {total} events, strength={strength}, "
                    f"top apps={top_apps[:5]}, top locations={top_locs[:3]}"
                )

        # reasoning_process intentionally omitted — see docstring.

        return "\n".join(lines) if lines else "No factual observations available from prior analysis"

    def _format_graph_insights(self, graph_context: dict) -> str:
        """Format graph context insights."""
        if not graph_context:
            return "No graph context available"

        lines = []

        # User patterns
        user_patterns = graph_context.get("user_patterns", {})
        if user_patterns:
            lines.append(f"User Patterns: {user_patterns}")

        # Related anomalies
        related_count = graph_context.get("related_anomalies_count", 0)
        if related_count > 0:
            lines.append(f"Related Anomalies: {related_count}")

        return "\n".join(lines) if lines else "No significant graph patterns"

    def _similarity_check(self, enriched_detection: dict, db_conn=None) -> dict:
        """
        Method 2: Similarity Check (weight: 0.30)

        Learn from similar labeled cases:
        - similar_detections IDs come from the ai_enrichment snapshot (set at enrichment time)
        - Labels (is_anomaly) are looked up LIVE from enriched_anomalies via db_conn
          because labeling happens AFTER enrichment — the snapshot is always label-free
        - Vote based on majority label of similar cases

        Requires db_conn to contribute. Without it the method always abstains
        (no db_conn = no labels = no signal).

        This is DATA-DRIVEN: learns from historical labels, no hardcoded rules.

        Returns:
            {"vote": true/false, "confidence": 0.0-1.0, "reasoning": "..."}
        """
        logger.info("   Method 2 (Similarity): Checking...")

        try:
            # Get similar detections from ai_enrichment snapshot
            ai_enrichment = enriched_detection.get("ai_enrichment", {})
            similar_detections = ai_enrichment.get("similar_detections", [])

            if not similar_detections:
                logger.info("      No similar cases found")
                return {"vote": False, "confidence": 0.0, "reasoning": "No similar cases — method abstains"}

            # Extract detection_ids (= anomaly_id UUIDs stored in Qdrant payload by persistence_service)
            top_k = self.config["similarity_top_k"]
            candidates = similar_detections[:top_k]
            detection_ids = [c.get("detection_id") for c in candidates if c.get("detection_id")]

            if not detection_ids:
                return {
                    "vote": False,
                    "confidence": 0.0,
                    "reasoning": "Similar cases have no detection_id — method abstains",
                }

            if not db_conn:
                # Without a live DB connection we cannot look up labels — abstain cleanly
                logger.info("      No db_conn provided — cannot look up labels, method abstains")
                return {
                    "vote": False,
                    "confidence": 0.0,
                    "reasoning": (
                        f"Found {len(similar_detections)} similar cases "
                        "but no db_conn provided for live label lookup — method abstains"
                    ),
                }

            # Live label lookup: read current is_anomaly from enriched_anomalies
            # Uses ANY(%s::uuid[]) for correct UUID array comparison in PostgreSQL
            with db_conn.cursor() as cur:
                cur.execute(
                    "SELECT anomaly_id::text, is_anomaly FROM enriched_anomalies WHERE anomaly_id = ANY(%s::uuid[])",
                    (detection_ids,),
                )
                label_map = {str(row[0]): row[1] for row in cur.fetchall()}

            labeled_cases = []
            for case in candidates:
                did = case.get("detection_id")
                is_anomaly = label_map.get(str(did)) if did else None
                if is_anomaly is not None:
                    labeled_cases.append(is_anomaly)

            if not labeled_cases:
                logger.info("      Similar cases found but none are labeled yet")
                return {
                    "vote": False,
                    "confidence": 0.0,
                    "reasoning": (
                        f"Found {len(similar_detections)} similar case(s) in enrichment snapshot "
                        f"(top-k={top_k}; {len(detection_ids)} ID(s) resolved) "
                        "but none have been labeled yet — method abstains"
                    ),
                }

            # Majority vote from similar cases
            false_positive_count = sum(1 for label in labeled_cases if not label)
            true_anomaly_count = sum(1 for label in labeled_cases if label)
            total = len(labeled_cases)

            # Vote with the majority
            if false_positive_count > true_anomaly_count:
                vote = False  # Similar cases are mostly false positives
                raw_confidence = false_positive_count / total
            else:
                vote = True  # Similar cases are mostly true anomalies
                raw_confidence = true_anomaly_count / total

            # Scale confidence by the score ratio: if the current event scores much
            # lower than the labeled similar events, reduce confidence proportionally.
            # Only apply the penalty on TRUE_ANOMALY votes — false-positive votes are
            # not score-dependent in the same way.
            current_score = float(enriched_detection.get("anomaly_score", 0.0))
            score_ratio_note = ""
            if vote and current_score > 0:
                true_cases = [c for c in candidates if label_map.get(str(c.get("detection_id"))) is True]
                if true_cases:
                    avg_similar_score = sum(float(c.get("anomaly_score", current_score)) for c in true_cases) / len(
                        true_cases
                    )
                    if avg_similar_score > 0:
                        score_ratio = min(current_score / avg_similar_score, 1.0)
                        score_ratio_note = (
                            f" Score ratio {current_score:.2f}/{avg_similar_score:.2f}={score_ratio:.2f}"
                            " (confidence scaled down)."
                            if score_ratio < 1.0
                            else ""
                        )
                        raw_confidence = round(raw_confidence * score_ratio, 2)

            confidence = raw_confidence

            reasoning = (
                f"Similar cases: {false_positive_count} false positives, "
                f"{true_anomaly_count} true anomalies (of {total} labeled). "
                f"Majority vote: {'TRUE ANOMALY' if vote else 'FALSE POSITIVE'}." + score_ratio_note
            )

            logger.info(f"      Similarity verdict: {vote} (confidence: {confidence:.2f})")

            return {"vote": vote, "confidence": confidence, "reasoning": reasoning}

        except Exception as e:
            logger.warning(f"   Method 2 (Similarity): Error - {e}")
            return {
                "vote": False,
                "confidence": 0.0,
                "reasoning": f"Similarity check failed — method abstains: {str(e)}",
            }

    def _graph_context(self, enriched_detection: dict) -> dict:
        """
        Method 3: Graph Context (weight: 0.20)

        Analyze historical patterns from Neo4j knowledge graph:
        - User's historical behavior patterns
        - Peer comparison (similar users in same role)
        - Related anomalies and their outcomes

        This is DATA-DRIVEN: learns from graph patterns, no hardcoded rules.

        Returns:
            {"vote": true/false, "confidence": 0.0-1.0, "reasoning": "..."}
        """
        logger.info("   Method 3 (Graph): Checking...")

        try:
            user_id = enriched_detection.get("user_id", "unknown")
            ai_enrichment = enriched_detection.get("ai_enrichment", {})
            graph_context = ai_enrichment.get("graph_context", {})

            if not graph_context:
                logger.info("      No graph context available")
                # confidence=0.0: no data → method abstains
                return {"vote": False, "confidence": 0.0, "reasoning": "No graph context available — method abstains"}

            # Analyze graph insights
            related_anomalies = graph_context.get("related_anomalies_count", 0)
            user_patterns = graph_context.get("user_patterns", {})
            patterns_note = f", patterns: {user_patterns}" if user_patterns else ""

            # Data-proportional confidence — no hardcoded count thresholds.
            # Confidence scales continuously with the count of related anomalies.
            # Formula: related / (related + 5) — Bayesian smoothing with prior of 5.
            # At 0 anomalies → confidence 0.0 (abstain); at 5 → 0.50; at 10 → 0.67; capped at 0.75.
            # TODO: Enhance with direct Neo4j queries for:
            # - Historical false positive rate for this user
            # - Peer comparison (users in same role)
            # - App/device/location relationship patterns

            if related_anomalies > 0:
                vote = True
                confidence = min(related_anomalies / (related_anomalies + 5.0), 0.75)
                reasoning = (
                    f"User {user_id} has {related_anomalies} related anomaly record(s) in stored graph context "
                    f"(recorded at enrichment time — may be capped by graph query limit; "
                    f"proportional confidence: {confidence:.2f}{patterns_note})"
                )
            else:
                vote = False
                confidence = 0.0  # No history → abstain, not evidence of false positive
                reasoning = (
                    f"User {user_id} has no related anomalies in stored graph context "
                    f"(enrichment-time snapshot) — method abstains (absence is not evidence{patterns_note})"
                )

            logger.info(f"      Graph verdict: {vote} (confidence: {confidence:.2f})")

            return {"vote": vote, "confidence": confidence, "reasoning": reasoning}

        except Exception as e:
            logger.warning(f"   Method 3 (Graph): Error - {e}")
            return {
                "vote": False,
                "confidence": 0.0,
                "reasoning": f"Graph context analysis failed — method abstains: {str(e)}",
            }

    def _ensemble_vote(self, votes: dict[str, dict]) -> dict:
        """
        Combine all method votes using weighted ensemble.

        Args:
            votes: Dict of method_name -> vote_result

        Returns:
            Final validation result with ensemble decision
        """
        # Calculate weighted score
        weighted_score = 0.0
        active_weight_sum = 0.0  # Sum of weights for methods that actually cast a vote
        reasoning_parts = []

        for method, weight in self.WEIGHTS.items():
            vote_result = votes.get(method, {})
            vote = vote_result.get("vote", False)  # Default False: missing result doesn't assert anomaly
            confidence = vote_result.get("confidence", 0.0)  # Default 0.0: missing result abstains

            # Convert boolean vote to numeric (1.0 = anomaly, 0.0 = false positive)
            vote_value = 1.0 if vote else 0.0

            # A method abstains when confidence == 0.0 — don't count its weight
            if confidence > 0.0:
                active_weight_sum += weight

            # Weight by method confidence
            contribution = vote_value * confidence * weight
            weighted_score += contribution

            # Build reasoning
            vote_str = "TRUE ANOMALY" if vote else "FALSE POSITIVE"
            reasoning_parts.append(f"{method.upper()}: {vote_str} (confidence: {confidence:.2f}, weight: {weight:.2f})")

        # Normalize score by active (non-abstaining) weights so that abstaining methods
        # don't artificially deflate the score relative to the fixed 0.5 threshold.
        # Example: LLM=0.70, Graph=0.75, Similarity abstains → raw=0.50, active=0.70, normalized=0.714
        if active_weight_sum > 0.0:
            normalized_score = weighted_score / active_weight_sum
        else:
            normalized_score = 0.0  # All methods abstained — no signal

        # Make final decision against normalized score
        is_anomaly = normalized_score >= self.ANOMALY_THRESHOLD

        # Confidence = distance from threshold on [0, 1] scale
        confidence = min(abs(normalized_score - self.ANOMALY_THRESHOLD) * 2, 1.0)

        active_methods = sum(1 for m in votes.values() if m.get("confidence", 0.0) > 0.0)

        # Post-ensemble safety gate: low-confidence TRUE ANOMALY decisions should not
        # carry the same weight as high-confidence ones.  When only one method voted
        # (e.g. LLM alone) and the final confidence is below 0.35, we cannot reliably
        # distinguish signal from noise — treat it as UNCERTAIN and flag for review.
        human_review_recommended = False
        if is_anomaly and confidence < 0.35 and active_methods <= 1:
            is_anomaly = None  # UNCERTAIN — BatchLabeler maps None → pending, not queued for retraining
            human_review_recommended = True
            logger.info(
                "      Post-ensemble gate: low confidence (%s) + single active method → "
                "downgraded to UNCERTAIN (human review recommended)",
                f"{confidence:.2f}",
            )

        # Build combined reasoning
        if human_review_recommended:
            decision_str = "UNCERTAIN — LOW CONFIDENCE (human review recommended)"
        else:
            decision_str = "TRUE ANOMALY" if is_anomaly else "FALSE POSITIVE"
        reasoning = f"""
Ensemble Validation: {decision_str}

Weighted Score: {weighted_score:.3f} → Normalized: {normalized_score:.3f} (threshold: {self.ANOMALY_THRESHOLD}, active methods: {active_methods}/{len(self.WEIGHTS)})
Final Confidence: {confidence:.2f}

Method Votes:
{chr(10).join(reasoning_parts)}

Interpretation:
- High confidence (>0.7): Strong agreement across methods
- Low confidence (<0.4): Mixed signals, recommend human review
- Single active method + confidence < 0.35: Downgraded to UNCERTAIN, flagged for review
""".strip()

        return {
            "is_anomaly": is_anomaly,
            "confidence": confidence,
            "reasoning": reasoning,
            "method": "ensemble",
            "votes": votes,
            "weighted_score": weighted_score,
            "normalized_score": normalized_score,
        }

    def __del__(self):
        """Cleanup resources."""
        if self._graph_service:
            self._graph_service.close()


# Command-line interface for testing
if __name__ == "__main__":
    import argparse

    import psycopg2
    import psycopg2.extras

    parser = argparse.ArgumentParser(description="Test anomaly validator")
    parser.add_argument("--detection-id", help="Specific detection ID to validate")
    parser.add_argument("--limit", type=int, default=10, help="Number of detections to validate")
    args = parser.parse_args()
    # LLM provider is read from LLM_PROVIDER in .env — no CLI override needed

    # Connection defaults match persistence_service.py (the pipeline source of truth).
    # Override any of these with env vars: POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB,
    #   POSTGRES_USER, POSTGRES_PASSWORD
    from modules.utils.db import get_db_params

    conn = psycopg2.connect(**get_db_params())

    with conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if args.detection_id:
                cur.execute(
                    "SELECT * FROM enriched_anomalies WHERE anomaly_id = %s",
                    (args.detection_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM enriched_anomalies
                    WHERE is_anomaly IS NULL
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (args.limit,),
                )
            detections = cur.fetchall()

        print(f"\nTesting Anomaly Validator on {len(detections)} detections\n")

        validator = AnomalyValidator()

        for detection in detections:
            # Pull prior analysis from llm_explanations (factual fields only — no verdicts)
            llm_explanation = None
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT context_analysis, pattern_analysis, evidence_summary,
                           entities_referenced, user_baseline_used, reasoning_process
                    FROM llm_explanations
                    WHERE detection_id = %s
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (detection["anomaly_id"],),
                )
                row = cur.fetchone()
                if row:
                    llm_explanation = dict(row)

            result = validator.validate(dict(detection), llm_explanation=llm_explanation, db_conn=conn)

            print(f"\n{'=' * 80}")
            print(f"Detection ID: {detection['anomaly_id']}")
            print(f"User:         {detection['user_id']}")
            print(f"Timestamp:    {detection['timestamp']}")
            print(f"Prior analysis available: {'yes' if llm_explanation else 'no'}")
            print(f"\n{result['reasoning']}")

            # Print individual method reasoning (useful for inspecting LLM quality)
            print(f"\n{'─' * 40}")
            print("Method Details:")
            for method_name, vote in result.get("votes", {}).items():
                print(f"\n  [{method_name.upper()}]")
                print(f"  Vote: {'TRUE ANOMALY' if vote['vote'] else 'FALSE POSITIVE'}")
                print(f"  Confidence: {vote['confidence']:.2f}")
                print(f"  Reasoning: {vote['reasoning']}")
            print(f"\n{'=' * 80}\n")
