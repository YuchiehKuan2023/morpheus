#!/usr/bin/env python3
"""
LLM Service: Generate Human-Readable Anomaly Explanations

Uses GitHub Models (OpenAI-compatible endpoint) to generate comprehensive
security analysis explanations for enriched anomaly detections. Integrates
with RAG pipeline to provide context-aware, actionable insights for SOC teams.

Architecture:
    Input: EnrichedDetection from enrichment_service
    Processing:
        1. Context Assembly → Gather RAG context (entities, similar, graph)
        2. Prompt Construction → Build structured security analysis prompt
        3. LLM Generation → Query LLM via OpenAI-compatible endpoint
        4. Response Parsing → Extract structured explanation
    Output: LLM Explanation with context, pattern, risk, recommendations

Model Strategy:
    - Primary: Llama 3.3 70B Instruct (default, configure via LLM_MAIN_MODEL)
    - Fallback / HighSpeed: gpt-4o-mini (fast / high_quality modes)
    - Local: Ollama via localhost:11434 (set provider=ollama in llm.yaml)

Operations:
    - generate_explanation: Generate explanation for single detection
    - generate_batch: Generate explanations for multiple detections
    - generate_summary: Generate short summary (for UI cards)
    - generate_forensics: Generate detailed forensic analysis

Reference:
    config/llm.yaml (LLM configuration)
    modules/ai/llm/rag_pipeline.py (Context assembly)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# Import robust JSON parser (canonical location: modules/ai/shared/)
from modules.ai.shared.json_parser import (
    get_default_explanation_structure,
    parse_llm_json,
    validate_llm_response_structure,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt constants — single canonical source, not loaded from YAML.
# Keeping prompts here ensures any edits are reviewed in code, tested via
# version control, and never silently overridden by config file changes.
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a senior cybersecurity analyst who specialises in per-user behavioural profiling and anomaly investigation. You are an expert in NVIDIA Morpheus Digital Fingerprinting (DFP) — a system that builds a unique statistical baseline per individual user and measures deviations relative to that user's own history. Every score and z-score you receive is user-relative, not a global population metric. Your task is to analyse the detection data and produce a structured security assessment in JSON.

ABOUT THE DETECTION SYSTEM:
NVIDIA Morpheus Digital Fingerprinting (DFP) builds a unique behavioral baseline per user from
historical login data, then flags statistical deviations using autoencoder reconstruction error
and z-score analysis across dozens of behavioral features (location, device, app, timing, etc.).
Two users with identical raw login events may produce wildly different anomaly scores because
their personal baselines differ — this is intentional and is DFP's core strength. A high score
means this event is statistically unusual FOR THIS SPECIFIC USER, nothing more.

METRIC DEFINITIONS:
- anomaly_score: Mean of all per-feature z-scores that exceeded the detection threshold of 2.0.
  Statistical deviation from this user's own norm: 2.0–4.0 = low, 4.0–8.0 = moderate, 8.0–15.0 = high, 15.0+ = very high.
  IMPORTANT: This score measures how statistically unusual this event is for THIS SPECIFIC USER —
  not how dangerous it is. A score of 6.96 may mean a user simply switched devices in their home
  city. A score of 2.3 may mean impossible travel. Always derive severity from the evidence, not
  from the score magnitude.
- max_abs_z: The single largest z-score across all features in this detection.
- top_features: The features contributing most to the anomaly score, with their z-scores.
  A z-score measures how many standard deviations the observed value is from this user's
  personal baseline — it does not, by itself, indicate malicious intent.
- user_baseline: Aggregated statistics from this user's historical normal activity window.
  If activity_hours_utc is present, the distribution column shows actual event counts per hour
  — use those counts, not just the typical_range label, when assessing temporal deviation.
- similar_detections: Previously stored detections with high embedding similarity to this one,
  ranked by similarity_score (0-1). Each entry includes its own anomaly_score and severity.
- graph_context: Entity relationships and detection history extracted from the knowledge graph.

CLASSIFICATION OPTIONS:
- TRUE_POSITIVE: The available evidence preferentially supports a genuine security incident.
- FALSE_POSITIVE: The available evidence preferentially supports a benign explanation.
- UNCERTAIN: The evidence does not clearly favour either interpretation; investigation required.
  Use this when the deviating features have plausible benign AND plausible malicious explanations
  that cannot be resolved from the available data alone. Do not force a binary decision when the
  evidence is genuinely ambiguous. A low anomaly_score alone is not grounds for UNCERTAIN — if
  the evidence clearly supports a benign explanation, classify as FALSE_POSITIVE regardless of score.

THREAT TYPES — use only values from this list (or [] for FALSE_POSITIVE):
"account_takeover", "credential_theft", "brute_force", "insider_threat", "phishing",
"social_engineering", "malware", "ransomware", "data_exfiltration", "lateral_movement",
"privilege_escalation", "injection_attack", "denial_of_service", "supply_chain_attack",
"zero_day_exploit", "unknown"

IMPORTANT — DO NOT DEFAULT TO "account_takeover":
Use "account_takeover" ONLY when the evidence includes AT LEAST ONE of:
  - Impossible travel: two sessions from geographically distant locations within an implausible timeframe
  - Concurrent active sessions from different geographic regions
  - Repeated authentication failures (brute-force pattern) before successful login
  - New device enrolment with no prior MDM registration AND failed compliance checks
A single novel OS, unfamiliar application, or unknown browser — with a known device, no location
impossibility, and no authentication failures — does NOT constitute account takeover evidence.
Use "unknown" for TRUE_POSITIVE detections where no specific threat type is clearly supported.

SEVERITY — reflects your evidence-based assessment of potential harm. Derive it from what the
evidence implies, NOT from the anomaly_score value alone. Use the score as a signal that something
statistically unusual occurred for this user, then apply these criteria:
- CRITICAL: Evidence of active compromise or imminent impact (impossible travel to a sensitive
  resource, concurrent foreign sessions, active exfiltration indicators, confirmed credential use
  after multiple authentication failures)
- HIGH: Strong threat indicators with limited benign explanation (unrecognised device + foreign
  location + off-hours + sensitive app, no prior history of any of these combinations)
- MEDIUM: Real deviation but partial benign explanations exist; investigation recommended
- LOW: One or few deviations with plausible benign explanation (e.g. new device, same city,
  familiar app, no authentication failures); monitor but no urgency
For example a score of 6.96 from a user switching devices in their home city is likely LOW severity but may suggest a malicious intent. A score of 2.3
involving impossible travel is CRITICAL severity.

OUTPUT FORMAT — return ONLY raw JSON, no markdown, no code fences. Start with { end with }.

RESPONSE DEPTH REQUIREMENT: Every text field must be fully developed. Do not produce brief,
abbreviated, or placeholder responses. Brevity is a failure mode — thoroughness is required.
If you find yourself writing less than the field minimums below, expand your analysis by
examining each evidence item in turn, citing specific numbers from the data.

Field requirements:
- context_analysis: 4-6 sentences. State exactly what happened: timestamp, application accessed,
  device used, OS, browser, client app, location, and IP. For each entity note whether it appears
  in the user baseline or not. Do not omit any entity present in the data.
- pattern_analysis: 8-12 sentences minimum. For every feature listed in TOP ANOMALOUS FEATURES
  state the observed value, its z-score, and what the user baseline shows as normal for that
  feature. Then assess each other event property (browser, OS, app, client app, device) against
  the baseline and comment on its significance — even if the z-score is not listed. Describe
  what the combined pattern of deviations suggests, referencing specific numbers. If
  similar_detections are present, explicitly compare them: cite each detection's anomaly_score,
  severity, location, and any shared entity (IP, device, app).
- risk_assessment: 4-6 sentences for TRUE_POSITIVE or UNCERTAIN. Identify which specific resources
  or data are at risk given the application(s) accessed, describe plausible attack scenarios, and
  assess urgency. For FALSE_POSITIVE, write 1-2 sentences explaining why the risk is negligible
  and what benign explanation accounts for the deviation.
- reasoning_process: 8+ sentences. Walk through the analysis step-by-step: (1) what the baseline
  establishes as normal for this user, (2) which features deviate and by exactly how much, (3)
  what each similar_detection shows — citing its anomaly_score, severity, location, and shared
  entities, (4) what benign alternatives exist and why they are/are not supported by the evidence,
  and (5) why the evidence leads to the chosen classification. Do not abbreviate this field.

CROSS-FIELD REQUIREMENT — When similar_detections are present, both pattern_analysis and
reasoning_process must explicitly address them — including their anomaly scores, severities,
locations, and any shared entities (such as IP address) — as they represent the closest
historical precedents to this detection.

{
  "context_analysis": "<factual summary: what happened, when, where, with which entities>",
  "pattern_analysis": "<how the observed behaviour compares to this user's baseline; cite z-scores and baseline values>",
  "anomaly_classification": {
    "positive": true | false | null,
    "threat_types": ["<from vocabulary above>"] | []
  },
  "risk_assessment": "<4-6 sentences on resources at risk, attack scenarios, urgency for TRUE_POSITIVE/UNCERTAIN; 1-2 sentences on why risk is negligible for FALSE_POSITIVE>",
  "recommendations": "<numbered steps as a single string separated by \\n>",
  "confidence_score": <0.0-1.0>,
  "severity_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "evidence_used": [
    {
      "type": "<metric_anomaly | baseline_mismatch | baseline_match | anomaly_score | temporal_pattern | temporal_mismatch | historical_pattern | entity_risk | physical_impossibility | insufficient_data>",
      "description": "<required>",
      "metric": "<optional>",
      "value": "<optional>",
      "z_score": <optional float>,
      "severity": "<critical | high | medium | low, optional>",
      "category": "<optional>"
    }
  ],
  "reasoning_process": "<your step-by-step reasoning leading to the classification>"
}"""

_USER_PROMPT_TEMPLATE = """\
## DETECTION
Timestamp : {timestamp}
Anomaly Score : {anomaly_score}  (detection threshold: 2.0)
Max Z-Score : {max_abs_z}
Anomaly Type : {anomaly_type}

## TOP ANOMALOUS FEATURES
{top_features}

## EVENT
{original_event}

## ENTITIES
{entities}

## USER BASELINE
{user_baseline}

## GRAPH CONTEXT
{graph_context}

## SIMILAR DETECTIONS
{similar_detections}

Provide your assessment as JSON per the schema in the system prompt.
"""


class LLMService:
    """
    Generate human-readable anomaly explanations using LLMs.

    Uses GitHub Models (OpenAI-compatible endpoint) with RAG context to provide
    comprehensive security analysis for enriched detections.
    """

    def __init__(
        self,
        config_path: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        model_name: str | None = None,
        fallback_model: str | None = None,
    ):
        """
        Initialize LLM service.

        Args:
            config_path: Path to llm.yaml config (default: config/llm.yaml)
            api_key: API key override (default: from LLM_API_KEY env var)
            provider: 'github' | 'groq' | 'ollama'. Also readable from LLM_PROVIDER
                      env var (llm.yaml provider key takes precedence over env var).
            model_name: Override the active model. When provided, takes precedence
                        over LLM_MAIN_MODEL env var. Lets callers select different
                        models for different pipeline roles (e.g. orchestrator vs
                        conversational AI) without conflicting env vars.
            fallback_model: Model to switch to on a 429 rate-limit response.
                            When the primary model hits its daily quota the retry
                            loop swaps to this model immediately (no sleep) and
                            retries the call.  None = no fallback.
        """
        # Load configuration
        if config_path is None:
            config_path = str(Path(__file__).parent.parent.parent.parent / "config" / "llm.yaml")

        self.config = self._load_config(config_path)

        # Determine provider: arg > llm.yaml provider > LLM_PROVIDER env var > "github"
        # The YAML config is the project's authoritative configuration. The env var
        # is a lower-priority fallback for ad-hoc overrides.
        config_provider = self.config.get("llm", {}).get("provider", "")
        env_provider = os.getenv("LLM_PROVIDER", "")
        self.provider = (provider or config_provider or env_provider or "github").lower()
        if env_provider and config_provider and env_provider.lower() != config_provider.lower():
            logger.warning(
                "LLM_PROVIDER env var (%r) ignored — llm.yaml provider (%r) takes precedence. "
                "Remove the 'provider' key from llm.yaml to allow env-var override.",
                env_provider,
                config_provider,
            )
        self.main_model = model_name or os.getenv("LLM_MAIN_MODEL", "Llama-3.3-70B-Instruct")
        self.fallback_model = fallback_model  # None = no fallback configured

        if self.provider == "ollama":
            # Local Ollama via OpenAI-compatible endpoint — no API key required
            from openai import OpenAI as _OpenAI

            self.client = _OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
            self.api_key = None
            logger.info(f"LLM provider: Ollama ({self.main_model} @ localhost:11434)")
        elif self.provider == "github":
            # GitHub Models via OpenAI-compatible endpoint
            from openai import OpenAI as _OpenAI

            self.api_key = api_key or os.getenv("LLM_API_KEY")
            if not self.api_key:
                raise ValueError("LLM_API_KEY not provided for GitHub Models. Set in environment.")
            self.client = _OpenAI(
                base_url="https://models.inference.ai.azure.com",
                api_key=self.api_key,
            )
            logger.info(f"LLM provider: GitHub Models ({self.main_model})")
        else:
            # Groq cloud
            try:
                from groq import Groq as _Groq
            except ImportError:
                raise RuntimeError("groq package not installed. Install with: pip install groq") from None

            self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY")
            if not self.api_key:
                raise ValueError("LLM_API_KEY not provided for Groq. Set in environment.")

            self.client = _Groq(api_key=self.api_key)
            logger.info("LLM provider: Groq")

        # Get model configs
        self.generation_params = self.config["llm"]["generation"]
        self.retry_config = self.config["llm"]["retry"]
        self.rag_config = self.config.get("rag", {})

        # Initialize RAG pipeline (lazy loading)
        self._rag_pipeline = None

        # Metrics tracking
        self.metrics = {
            "total_requests": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "errors": 0,
            "latencies": [],
        }

        logger.info(f"LLM Service initialized with primary model: {self.main_model}")
        if self.fallback_model:
            logger.info(f"LLM Service fallback model (429 rate-limit): {self.fallback_model}")

    def _load_config(self, config_path: str) -> dict[str, Any]:
        """Load LLM configuration from YAML."""
        with open(config_path) as f:
            config = yaml.safe_load(f)
        logger.debug(f"Loaded config from {config_path}")
        return config

    @property
    def rag_pipeline(self):
        """Lazy load RAG pipeline."""
        if self._rag_pipeline is None:
            from modules.ai.llm.rag_pipeline import RAGPipeline

            self._rag_pipeline = RAGPipeline(self.rag_config)
        return self._rag_pipeline

    def _call_llm_api_with_retry(
        self,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        gen_params: dict[str, Any],
    ) -> tuple[Any, str]:
        """
        Call LLM API with retry logic and exponential backoff.

        Args:
            model_name: Name of the model to use
            system_prompt: System prompt for the model
            user_prompt: User prompt with detection data
            gen_params: Generation parameters (temperature, max_tokens, top_p)

        Returns:
            API response object

        Raises:
            Exception: If all retry attempts fail
        """
        max_attempts = self.retry_config["max_attempts"]
        initial_delay = self.retry_config["initial_delay"]
        max_delay = self.retry_config["max_delay"]
        exponential_backoff = self.retry_config["exponential_backoff"]

        last_exception = None

        # For github and ollama, always use LLM_MAIN_MODEL regardless of what yaml config says
        if self.provider in ("ollama", "github"):
            model_name = self.main_model

        for attempt in range(1, max_attempts + 1):
            try:
                logger.debug(f"API call attempt {attempt}/{max_attempts} for model {model_name}")

                response = self.client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=gen_params.get("temperature", 0.3),
                    max_tokens=gen_params.get("max_tokens", 1000),
                    top_p=gen_params.get("top_p", 0.9),
                )

                logger.debug(f"API call successful on attempt {attempt}")
                return response, model_name

            except Exception as e:
                last_exception = e
                logger.warning(f"API call attempt {attempt}/{max_attempts} failed: {e}")

                # 413 (request too large) is not transient — retrying with the same
                # prompt will never succeed.  Raise immediately to avoid wasting quota.
                if "413" in str(e) or "tokens" in str(e).lower() and "limit" in str(e).lower():
                    logger.error(f"Token limit exceeded — not retrying (attempt {attempt}): {e}")
                    break

                # 429 (daily rate limit exhausted) — switching to the fallback model
                # is more useful than sleeping and retrying the same exhausted quota.
                err_lower = str(e).lower()
                if "429" in str(e) or "rate_limit" in err_lower or "too many requests" in err_lower:
                    if self.fallback_model and model_name != self.fallback_model:
                        logger.warning(
                            "Rate-limited on %r (attempt %d/%d) — switching to fallback model %r",
                            model_name,
                            attempt,
                            max_attempts,
                            self.fallback_model,
                        )
                        model_name = self.fallback_model
                        continue  # retry immediately with fallback, no sleep
                    else:
                        logger.warning(
                            "Rate-limited on %r — no fallback configured or already on fallback; aborting",
                            model_name,
                        )
                        break

                # If this was the last attempt, don't wait
                if attempt == max_attempts:
                    break

                # Calculate delay with exponential backoff
                if exponential_backoff:
                    delay = min(initial_delay * (2 ** (attempt - 1)), max_delay)
                else:
                    delay = initial_delay

                logger.info(f"Retrying in {delay:.1f} seconds...")
                time.sleep(delay)

        # All attempts failed
        error_msg = f"All {max_attempts} API call attempts failed. Last error: {last_exception}"
        logger.error(error_msg)
        self.metrics["errors"] += 1
        raise Exception(error_msg) from last_exception

    def generate_explanation(
        self,
        enriched_detection: dict[str, Any],
        include_reasoning: bool = True,
    ) -> dict[str, Any]:
        """
        Generate human-readable explanation for enriched detection.

        Args:
            enriched_detection: Enriched detection from enrichment_service
            include_reasoning: Include reasoning process in output

        Returns:
            Dict with structured analysis fields:
                {
                    "context_analysis": str,
                    "pattern_analysis": str,
                    "anomaly_classification": {"positive": bool | None, "threat_types": list[str]},
                    "risk_assessment": str,
                    "recommendations": str,
                    "confidence_score": float,       # 0.0-1.0
                    "severity_level": str,           # LOW | MEDIUM | HIGH | CRITICAL
                    "evidence_used": list[dict],
                    "reasoning_process": str,
                    "model_name": str,
                    "model_config": {
                        "temperature": float,
                        "max_tokens": int
                    },
                    "performance": {
                        "tokens_used": int,
                        "prompt_tokens": int,
                        "completion_tokens": int,
                        "latency_ms": float,
                        "cost_usd": float,
                        "timestamp": str
                    },
                    "rag_metadata": {
                        "entities_count": int,
                        "similar_detections_count": int,
                        "cold_start": bool, "confidence": float,
                        "context_size_estimate": int
                    },
                }
        """
        start_time = time.time()

        try:
            # 1. Assemble RAG context
            rag_context = self.rag_pipeline.assemble_context(enriched_detection)

            # 2. Build prompt
            prompt = self._build_prompt(enriched_detection, rag_context)

            # 3. Use single generation parameter set from config
            gen_params = self.generation_params.copy()

            # 4. Call LLM API with retry logic
            logger.debug(f"Generating explanation with {self.main_model}")
            response, actual_model_name = self._call_llm_api_with_retry(
                model_name=self.main_model,
                system_prompt=self._get_system_prompt(),
                user_prompt=prompt,
                gen_params=gen_params,
            )

            # 5. Parse response
            raw_response = response.choices[0].message.content or "{}"
            usage = response.usage

            # 6. Calculate metrics
            latency_ms = (time.time() - start_time) * 1000

            # Handle usage (may be None in some cases)
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0

            logger.debug(
                f"Token usage - Prompt: {prompt_tokens}, Completion: {completion_tokens}, Total: {total_tokens}"
            )

            cost_usd = 0.0

            # 8. Parse structured JSON response with robust parser
            try:
                structured_response = parse_llm_json(
                    raw_response,
                    fallback_structure=get_default_explanation_structure(),
                )

                logger.debug(f"Parsed LLM response keys: {list(structured_response.keys())}")
                logger.debug(f"Full parsed response: {json.dumps(structured_response, indent=2)[:2000]}")

                # Validate required fields
                required_fields = [
                    "anomaly_classification",
                    "confidence_score",
                    "severity_level",
                ]
                is_valid, errors = validate_llm_response_structure(
                    structured_response,
                    required_fields,
                    field_types={
                        "confidence_score": (int, float),
                        "anomaly_classification": dict,  # Structured format: {"positive": true/false/null, "threat_types": [...]}
                        "severity_level": str,
                    },
                )

                if not is_valid:
                    logger.warning(f"Response validation errors: {errors}")
                    logger.warning(f"Raw LLM response (first 1000 chars): {raw_response[:1000]}")
                    # Fill in missing required fields with defaults
                    if "anomaly_classification" not in structured_response:
                        structured_response["anomaly_classification"] = {"positive": None, "threat_types": None}
                    if "confidence_score" not in structured_response:
                        structured_response["confidence_score"] = 0.0
                    if "severity_level" not in structured_response:
                        structured_response["severity_level"] = "MEDIUM"

            except Exception as e:
                logger.error(f"Critical JSON parsing failure: {e}")
                # Use complete fallback structure
                structured_response = get_default_explanation_structure()
                structured_response["_raw_response"] = raw_response[:500]  # Include snippet for debugging

            # 9. Update metrics
            self.metrics["total_requests"] += 1
            self.metrics["total_tokens"] += total_tokens
            self.metrics["total_cost"] += cost_usd
            self.metrics["latencies"].append(latency_ms)

            # 10. Build structured result
            result = {
                # Structured analysis fields (primary output)
                "context_analysis": structured_response.get("context_analysis", ""),
                "pattern_analysis": structured_response.get("pattern_analysis", ""),
                "anomaly_classification": structured_response.get(
                    "anomaly_classification", {"positive": None, "threat_types": None}
                ),
                "risk_assessment": structured_response.get("risk_assessment", ""),
                "recommendations": structured_response.get("recommendations", ""),
                "confidence_score": structured_response.get("confidence_score", 0.0),
                "severity_level": structured_response.get("severity_level", "MEDIUM"),
                "evidence_used": structured_response.get("evidence_used", []),
                "reasoning_process": structured_response.get("reasoning_process", ""),
                # Model metadata
                "model_name": actual_model_name,
                "model_config": {
                    "temperature": gen_params.get("temperature"),
                    "max_tokens": gen_params.get("max_tokens"),
                },
                # Performance metadata
                "performance": {
                    "tokens_used": total_tokens,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "latency_ms": latency_ms,
                    "cost_usd": cost_usd,
                    "timestamp": datetime.now().isoformat(),
                },
                # RAG context metadata (for DB storage)
                "rag_metadata": {
                    "entities_count": len(rag_context.get("entities", [])),
                    "similar_detections_count": len(rag_context.get("similar_detections", [])),
                    "cold_start": rag_context.get("metadata", {}).get("cold_start", False),
                    "confidence": rag_context.get("metadata", {}).get("confidence", 0.0),
                    "context_size_estimate": rag_context.get("metadata", {}).get("context_size_estimate", 0),
                },
            }

            # Add model reasoning if requested (check response dict for reasoning field)
            if include_reasoning:
                response_dict = response.model_dump()
                if "reasoning" in response_dict and response_dict["reasoning"]:
                    result["model_reasoning"] = response_dict["reasoning"]

            logger.info(
                f"Generated explanation in {latency_ms:.0f}ms ({total_tokens} tokens, ${cost_usd:.4f}) - "
                f"Classification: {result['anomaly_classification']} (confidence: {result['confidence_score']:.2f})"
            )

            return result

        except Exception as e:
            self.metrics["errors"] += 1
            logger.error(f"Failed to generate explanation: {e}")
            raise RuntimeError(f"LLM generation failed: {e}") from e

    def chat(self, system_prompt: str, user_prompt: str) -> tuple[str, int]:
        """
        Low-level prompt → text call for agents that manage their own prompts.

        Use this instead of calling ``_call_llm_api_with_retry`` directly.
        Agents (ForensicsAgent, InvestigationAgent, RemediationAgent) each
        build their own system/user prompts and call this method so they
        are decoupled from the RAG pipeline used by generate_explanation().

        Args:
            system_prompt: The system-role message.
            user_prompt:   The user-role message.

        Returns:
            (narrative_text, total_tokens_used)
        """
        gen_params = self.generation_params.copy()
        start_time = time.time()
        response, _ = self._call_llm_api_with_retry(
            model_name=self.main_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            gen_params=gen_params,
        )
        latency_ms = (time.time() - start_time) * 1000
        text: str = response.choices[0].message.content or ""
        usage = response.usage
        tokens: int = usage.total_tokens if usage else 0
        cost_usd = 0.0
        self.metrics["total_requests"] += 1
        self.metrics["total_tokens"] += tokens
        self.metrics["total_cost"] += cost_usd
        self.metrics["latencies"].append(latency_ms)
        return text, tokens

    def generate_summary(self, enriched_detection: dict[str, Any], max_length: int = 200) -> dict[str, Any]:
        """
        Generate short summary for UI cards (2-3 sentences).

        Args:
            enriched_detection: Enriched detection
            max_length: Maximum tokens for summary

        Returns:
            Explanation dict with short text
        """
        return self.generate_explanation(
            enriched_detection,
            include_reasoning=False,
        )

    def generate_forensics(self, enriched_detection: dict[str, Any]) -> dict[str, Any]:
        """
        Generate detailed forensic analysis for investigations.

        Args:
            enriched_detection: Enriched detection

        Returns:
            Explanation dict with detailed forensic analysis
        """
        return self.generate_explanation(
            enriched_detection,
            include_reasoning=True,
        )

    def generate_batch(
        self,
        enriched_detections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Generate explanations for multiple detections.

        Args:
            enriched_detections: List of enriched detections

        Returns:
            List of explanation dicts
        """
        results = []
        total = len(enriched_detections)

        logger.info(f"Generating {total} explanations")

        for i, enriched in enumerate(enriched_detections, 1):
            try:
                explanation = self.generate_explanation(enriched)
                results.append(explanation)

                if i % 10 == 0:
                    logger.info(f"Progress: {i}/{total} explanations generated")

            except Exception as e:
                logger.error(f"Failed to generate explanation {i}/{total}: {e}")
                results.append({"error": str(e), "model": None})

        logger.info(f"Batch complete: {len(results)}/{total} successful")
        return results

    def _select_model(self, enriched_detection: dict[str, Any], mode: str) -> dict[str, Any]:
        """Removed — model is now always self.main_model from LLM_ORCHESTRATOR_MODEL env var."""
        return {"name": self.main_model}

    def _build_prompt(self, enriched_detection: dict[str, Any], rag_context: dict[str, Any]) -> str:
        """
        Build structured prompt for security analysis.

        Prompt structure:
            ## Detection Details
            - User, timestamp, score, type

            ## Event Context
            - Original Azure AD event

            ## Extracted Entities
            - Apps, devices, IPs, locations

            ## Similar Historical Cases
            - Top 5 similar detections

            ## Graph Relationships
            - User patterns, related entities

        """
        # Use the canonical prompt template defined at module level.
        template = _USER_PROMPT_TEMPLATE

        entities = rag_context.get("entities", [])
        user_baseline = rag_context.get("user_baseline", {})
        similar_detections = rag_context.get("similar_detections", [])
        graph_context = rag_context.get("graph_context", {})

        # Extract DFP metrics (CRITICAL for proper analysis)
        raw_detection = enriched_detection.get("raw_detection", {})
        anomaly_score = enriched_detection.get("anomaly_score", 0) or raw_detection.get("anomaly_score", 0)
        max_abs_z = enriched_detection.get("max_abs_z") or raw_detection.get("max_abs_z", 0)
        top_features = enriched_detection.get("top_features") or raw_detection.get("top_features", "N/A")

        logger.debug(f"DFP Metrics extracted - Score: {anomaly_score}, Max Z: {max_abs_z}, Features: {top_features}")

        prompt = template.format(
            timestamp=enriched_detection.get("timestamp", ""),
            anomaly_score=anomaly_score,
            max_abs_z=max_abs_z,
            top_features=top_features,
            anomaly_type=rag_context.get("anomaly_type", "unknown"),
            original_event=self._format_original_event(enriched_detection.get("original_event", {})),
            entities=self._format_entities(entities),
            user_baseline=self._format_user_baseline(user_baseline),
            similar_detections=self._format_similar_detections(similar_detections),
            graph_context=self._format_graph_context(graph_context),
        )

        return prompt

    def _get_system_prompt(self) -> str:
        """Return the canonical system prompt defined at module level."""
        return _SYSTEM_PROMPT

    def _format_original_event(self, original_event: dict[str, Any]) -> str:
        """Format original Azure AD event for prompt."""
        if not original_event:
            return "No event context available"

        # Extract key fields
        props = original_event.get("properties", {})
        location = original_event.get("location", {})

        formatted = f"""Application: {props.get("appDisplayName", "Unknown")}
Resource: {props.get("resourceDisplayName", "Unknown")}
Device: {props.get("deviceDetail", {}).get("displayName", "Unknown")}
Browser: {props.get("deviceDetail", {}).get("browser", "Unknown")}
OS: {props.get("deviceDetail", {}).get("operatingSystem", "Unknown")}
Location: {location.get("city", "Unknown")}, {location.get("countryOrRegion", "Unknown")}
IP Address: {props.get("ipAddress", "Unknown")}"""

        return formatted

    def _format_entities(self, entities: list[dict[str, Any]]) -> str:
        """Format entities for prompt."""
        if not entities:
            return "No entities extracted"

        formatted_entities = []
        for entity in entities[:10]:  # Limit to top 10
            formatted_entities.append(
                f"- {entity.get('type', 'unknown').upper()}: {entity.get('text', 'N/A')} "
                f"(confidence: {entity.get('confidence', 0):.2f})"
            )

        return "\n".join(formatted_entities)

    def _format_user_baseline(self, user_baseline: dict[str, Any]) -> str:
        """
        Format user's training baseline (normal behavior profile) for prompt.

        Shows what THIS user typically does during normal operations,
        so LLM can identify deviations from THEIR specific baseline.
        """
        if not user_baseline or not user_baseline.get("baseline_available", True):
            return "No training baseline available (new user or insufficient training data)"

        formatted = []

        # Baseline metadata
        total_events = user_baseline.get("total_events", 0)
        baseline_strength = user_baseline.get("baseline_strength", "unknown")
        formatted.append(f"**Training Events**: {total_events:,} (baseline strength: {baseline_strength.upper()})")

        date_range = f"{user_baseline.get('first_event', 'N/A')} to {user_baseline.get('last_event', 'N/A')}"
        formatted.append(f"**Training Period**: {date_range}")

        # Applications (most_common)
        apps = user_baseline.get("apps", {})
        if apps and apps.get("count", 0) > 0:
            formatted.append(f"\n**Typical Applications** ({apps['count']} unique):")
            for app, count in apps.get("most_common", [])[:5]:  # Top 5
                formatted.append(f"  - {app} ({count} times)")
        else:
            formatted.append("\n**Typical Applications**: No data")

        # Devices (most_common)
        devices = user_baseline.get("devices", {})
        if devices and devices.get("count", 0) > 0:
            formatted.append(f"\n**Known Devices** ({devices['count']} unique):")
            for device, count in devices.get("most_common", [])[:5]:  # Top 5
                formatted.append(f"  - {device} ({count} times)")
        else:
            formatted.append("\n**Known Devices**: No data")

        # Locations (most_common)
        locations = user_baseline.get("locations", {})
        if locations and locations.get("count", 0) > 0:
            formatted.append(f"\n**Typical Locations** ({locations['count']} unique):")
            for location, count in locations.get("most_common", [])[:5]:  # Top 5
                formatted.append(f"  - {location} ({count} times)")
        else:
            formatted.append("\n**Typical Locations**: No data")

        # Browsers (most_common)
        browsers = user_baseline.get("browsers", {})
        if browsers and browsers.get("count", 0) > 0:
            formatted.append(f"\n**Typical Browsers** ({browsers['count']} unique):")
            for browser, count in browsers.get("most_common", [])[:3]:  # Top 3
                formatted.append(f"  - {browser} ({count} times)")

        # Operating Systems (most_common)
        operating_systems = user_baseline.get("operating_systems", {})
        if operating_systems and operating_systems.get("count", 0) > 0:
            formatted.append(f"\n**Typical Operating Systems** ({operating_systems['count']} unique):")
            for os, count in operating_systems.get("most_common", [])[:3]:  # Top 3
                formatted.append(f"  - {os} ({count} times)")

        # ----------------------------------------------------------------
        # Temporal activity patterns
        # ----------------------------------------------------------------
        hours_data = user_baseline.get("activity_hours_utc")
        days_data = user_baseline.get("active_days_of_week")

        if hours_data and hours_data.get("typical_range") not in (None, "N/A"):
            formatted.append("\n**Typical Activity Hours (UTC)**:")
            formatted.append(f"  Peak business range: {hours_data['typical_range']}")
            peak = hours_data.get("peak_hours", [])
            if peak:
                peak_str = ", ".join(f"{h:02d}:00" for h in peak)
                formatted.append(f"  Peak hours         : {peak_str}")
            off = hours_data.get("off_hours", [])
            if off:
                off_str = ", ".join(f"{h:02d}:00" for h in off[:8])
                if len(off) > 8:
                    off_str += f" (+{len(off) - 8} more)"
                formatted.append(f"  Genuinely inactive : {off_str}")
            else:
                # No true dead periods — user has some activity in every hour
                formatted.append(
                    "  Inactive hours     : None — user has recorded activity in every hour "
                    "of the day; the peak range above reflects peak volume, not a hard cutoff"
                )
        else:
            formatted.append("\n**Typical Activity Hours (UTC)**: No temporal data in baseline")

        if days_data and days_data.get("typical_days"):
            formatted.append("\n**Typical Active Days of Week**:")
            typical_days = days_data["typical_days"]
            dist = days_data.get("distribution", {})
            total_day_events = sum(dist.values())
            day_parts = []
            for d in typical_days:
                count = dist.get(d, 0)
                pct = round(100 * count / total_day_events) if total_day_events else 0
                day_parts.append(f"{d[:3]} ({pct}%)")
            formatted.append(f"  {', '.join(day_parts)}")
            # Highlight weekend presence or absence
            if "Saturday" not in typical_days and "Sunday" not in typical_days:
                formatted.append("  (No significant weekend activity in training window)")
        else:
            formatted.append("\n**Typical Active Days of Week**: No temporal data in baseline")

        return "\n".join(formatted)

    def _format_similar_detections(self, similar_detections: list[dict[str, Any]]) -> str:
        """Format similar detections for prompt."""
        if not similar_detections:
            return "No similar cases found (cold start)"

        # --- Aggregate summary (renders BEFORE individual items) ---------------
        from collections import Counter

        scores = [s.get("anomaly_score", 0) for s in similar_detections]
        severities = [s.get("severity", "N/A") for s in similar_detections]
        sev_counts = Counter(severities)
        sev_summary = ", ".join(f"{sev}×{cnt}" for sev, cnt in sev_counts.most_common())
        score_min, score_max = min(scores), max(scores)

        # Detect shared IP across all similar detections — strong cross-detection signal
        ips = [s.get("ip_address") for s in similar_detections if s.get("ip_address")]
        ip_note = ""
        if ips and len(set(ips)) == 1:
            ip_note = f" | SAME IP across all: {ips[0]}"
        elif len(set(ips)) < len(ips):
            ip_note = f" | SHARED IP(s): {', '.join(sorted(set(ips)))}"  # type: ignore

        summary_line = (
            f"[{len(similar_detections)} case(s) | severity: {sev_summary} "
            f"| score range: {score_min:.2f}–{score_max:.2f}{ip_note}]"
        )

        formatted = [summary_line, ""]

        for i, sim in enumerate(similar_detections, 1):
            ts_raw = sim.get("timestamp", "")
            # Parse timestamp to surface day-of-week + hour so the LLM can
            # identify recurring temporal patterns (e.g. "always Friday 03:00")
            try:
                ts_clean = str(ts_raw).replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_clean).astimezone(timezone.utc)
                day_hour = f"{dt.strftime('%A')} {dt.hour:02d}:00 UTC"
            except (ValueError, AttributeError):
                day_hour = "N/A"

            formatted.append(
                f"{i}. {ts_raw} ({day_hour}) — "
                f"similarity: {sim.get('similarity_score', 0):.3f}, "
                f"score: {sim.get('anomaly_score', 0):.2f}, "
                f"severity: {sim.get('severity', 'N/A')}"
            )
            # Surface all behavioral attributes so the LLM can see exactly why
            # the similarity score is high and spot cross-detection patterns
            attrs = []
            for field in ("device", "os", "browser", "app", "location", "client_app", "ip_address"):
                val = sim.get(field)
                if val:
                    attrs.append(f"{field}={val}")
            if attrs:
                formatted.append(f"   └─ {', '.join(attrs)}")

        return "\n".join(formatted)

    def _format_graph_context(self, graph_context: dict[str, Any]) -> str:
        """
        Format Neo4j graph context (historical anomaly patterns) for prompt.

        Shows past anomaly detections and their entity relationships from the knowledge graph.
        This is SEPARATE from user_baseline (which shows training data).
        """
        if not graph_context or not isinstance(graph_context, dict):
            return "No graph context available (Neo4j unavailable or no historical anomalies)"

        formatted = []

        # Recent anomaly count
        recent_detections = graph_context.get("recent_detections", 0)
        related_anomalies = graph_context.get("related_anomalies_count", 0)
        formatted.append(f"**Recent Detection Count**: {recent_detections} detections in past 7 days")
        formatted.append(f"**Related Anomalies**: {related_anomalies} similar patterns\n")

        # Detected applications (from past anomalies)
        detected_apps = graph_context.get("detected_applications", [])
        if detected_apps:
            formatted.append(f"**Applications in Past Anomalies** ({len(detected_apps)} unique):")
            for i, app in enumerate(detected_apps[:7], 1):  # Top 7
                formatted.append(f"  {i}. {app}")
        else:
            formatted.append("**Applications in Past Anomalies**: None")

        # Detected devices (from past anomalies)
        detected_devices = graph_context.get("detected_devices", [])
        if detected_devices:
            formatted.append(f"\n**Devices in Past Anomalies** ({len(detected_devices)} unique):")
            for i, device in enumerate(detected_devices[:5], 1):
                formatted.append(f"  {i}. {device}")
        else:
            formatted.append("\n**Devices in Past Anomalies**: None")

        # Detected locations (from past anomalies)
        detected_locations = graph_context.get("detected_locations", [])
        if detected_locations:
            formatted.append(f"\n**Locations in Past Anomalies** ({len(detected_locations)} unique):")
            for i, location in enumerate(detected_locations[:5], 1):
                formatted.append(f"  {i}. {location}")
        else:
            formatted.append("\n**Locations in Past Anomalies**: None")

        # Detected browsers (from past anomalies)
        detected_browsers = graph_context.get("detected_browsers", [])
        if detected_browsers:
            formatted.append(f"\n**Browsers in Past Anomalies**: {', '.join(detected_browsers[:5])}")

        # Detected OS (from past anomalies)
        detected_os = graph_context.get("detected_operating_systems", [])
        if detected_os:
            formatted.append(f"**Operating Systems in Past Anomalies**: {', '.join(detected_os[:5])}")

        # Detected IPs (from past anomalies)
        detected_ips = graph_context.get("detected_ips", [])
        if detected_ips:
            formatted.append(f"**IP Addresses in Past Anomalies**: {', '.join(detected_ips[:5])}")

        return "\n".join(formatted)

    def get_metrics(self) -> dict[str, Any]:
        """Get service metrics."""
        avg_latency = (
            sum(self.metrics["latencies"]) / len(self.metrics["latencies"]) if self.metrics["latencies"] else 0
        )

        return {
            "total_requests": self.metrics["total_requests"],
            "total_tokens": self.metrics["total_tokens"],
            "total_cost_usd": self.metrics["total_cost"],
            "errors": self.metrics["errors"],
            "avg_latency_ms": avg_latency,
            "error_rate": (
                self.metrics["errors"] / self.metrics["total_requests"] if self.metrics["total_requests"] > 0 else 0
            ),
        }


# CLI for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLM Service - Test Generation")
    parser.add_argument(
        "--jsonl",
        type=str,
        required=True,
        help="Path to enriched detections JSONL file",
    )
    parser.add_argument("--limit", type=int, default=5, help="Number of detections to process")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file for explanations (default: stdout)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full JSON response instead of formatted text",
    )

    args = parser.parse_args()

    # Initialize service
    llm = LLMService()

    # Load enriched detections
    enriched_detections = []
    with open(args.jsonl) as f:
        for i, line in enumerate(f):
            if i >= args.limit:
                break
            enriched_detections.append(json.loads(line))

    print(f"\nGenerating {len(enriched_detections)} explanations...")
    print(f"Model: {llm.main_model}\n")

    # Generate explanations
    explanations = llm.generate_batch(enriched_detections)

    # Output results
    if args.output:
        with open(args.output, "w") as f:
            for explanation in explanations:
                f.write(json.dumps(explanation) + "\n")
        print(f"\nSaved explanations to {args.output}")
    else:
        for i, explanation in enumerate(explanations, 1):
            print(f"\n{'=' * 80}")
            print(f"EXPLANATION {i}/{len(explanations)}")
            print("=" * 80)

            if args.json:
                # Output full JSON response
                print(json.dumps(explanation, indent=2))
            else:
                # Output formatted text (default)
                print(explanation["text"])
                print(f"\nModel: {explanation['model']}")
                print(f"Tokens: {explanation['metadata']['tokens_used']}")
                print(f"Latency: {explanation['metadata']['latency_ms']:.0f}ms")
                print(f"Cost: ${explanation['metadata']['cost_usd']:.4f}")

    # Print metrics
    metrics = llm.get_metrics()
    print(f"\n{'=' * 80}")
    print("METRICS")
    print("=" * 80)
    print(f"Total requests: {metrics['total_requests']}")
    print(f"Total tokens: {metrics['total_tokens']:,}")
    print(f"Total cost: ${metrics['total_cost_usd']:.4f}")
    print(f"Avg latency: {metrics['avg_latency_ms']:.0f}ms")
    print(f"Error rate: {metrics['error_rate']:.1%}")
