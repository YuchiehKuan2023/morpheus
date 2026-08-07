#!/usr/bin/env python3
"""
LLM Explanation Database Persistence

Maps LLM service response (10 fields) to llm_explanations table (47 columns).
Handles all metadata extraction, JSON array conversion, and performance tracking.

Usage:
    >>> from modules.ai.llm.db_persistence import save_llm_explanation
    >>>
    >>> explanation = llm_service.generate_explanation(enriched_detection)
    >>> save_llm_explanation(
    ...     conn=db_connection,
    ...     detection_id=detection.id,
    ...     explanation=explanation,
    ...     enriched_detection=enriched_detection
    ... )

Author: AI Intelligence Layer Team
Date: 2026-02-23
"""

import logging
from typing import Any
from uuid import UUID

import psycopg2
from psycopg2.extras import Json

logger = logging.getLogger(__name__)


def save_llm_explanation(
    conn: psycopg2.extensions.connection,
    detection_id: UUID | str,
    explanation: dict[str, Any],
    enriched_detection: dict[str, Any],
    explanation_type: str = "detailed",
) -> int:
    """
    Save LLM explanation to llm_explanations table.

    Maps LLM response fields to database columns with full metadata.

    Args:
        conn: PostgreSQL database connection
        detection_id: UUID of the detection
        explanation: LLM service response dict
        enriched_detection: Original enriched detection (for RAG metadata)
        explanation_type: Type of explanation ('summary', 'detailed', 'forensics')

    Returns:
        int: ID of inserted explanation record

    Raises:
        psycopg2.Error: If database operation fails
    """
    cursor = conn.cursor()

    try:
        # Extract LLM response fields
        context_analysis = explanation.get("context_analysis")
        pattern_analysis = explanation.get("pattern_analysis")

        # Extract structured anomaly_classification (dict with positive + threat_types)
        anomaly_classification_raw = explanation.get("anomaly_classification")
        if isinstance(anomaly_classification_raw, dict):
            # Structured format: {"positive": true/false/null, "threat_types": [...]}
            anomaly_classification = Json(anomaly_classification_raw)
        else:
            # Invalid format, default to uncertain
            logger.warning(f"Invalid anomaly_classification format: {type(anomaly_classification_raw)}. Expected dict.")
            anomaly_classification = Json({"positive": None, "threat_types": None})

        risk_assessment = explanation.get("risk_assessment")
        recommendations = explanation.get("recommendations")
        confidence_score = explanation.get("confidence_score")
        severity_level = explanation.get("severity_level")
        reasoning_process = explanation.get("reasoning_process")
        evidence_used = explanation.get("evidence_used", [])

        # Extract model metadata
        model_name = explanation.get("model_name")
        model_config = explanation.get("model_config", {})
        temperature = model_config.get("temperature")
        max_tokens = model_config.get("max_tokens")

        # Extract performance metadata
        performance = explanation.get("performance", {})
        prompt_tokens = performance.get("prompt_tokens", 0)
        completion_tokens = performance.get("completion_tokens", 0)
        total_tokens = performance.get("tokens_used", 0)
        cost_usd = performance.get("cost_usd", 0.0)
        latency_ms = performance.get("latency_ms", 0.0)

        # Extract RAG metadata
        rag_metadata = explanation.get("rag_metadata", {})
        entities_count = rag_metadata.get("entities_count", 0)
        similar_detections_count = rag_metadata.get("similar_detections_count", 0)
        cold_start = rag_metadata.get("cold_start", False)
        rag_context_size = rag_metadata.get("context_size_estimate", 0)

        # Build evidence summary (keep as structured JSON array for frontend)
        evidence_summary = Json(evidence_used) if evidence_used else None

        # Extract entities, similar cases, user baseline, and graph insights from enriched detection
        ai_enrichment = enriched_detection.get("ai_enrichment", {})
        entities_referenced = Json(ai_enrichment.get("entities", [])[:10])  # Top 10
        similar_cases_cited = Json(ai_enrichment.get("similar_detections", [])[:5])  # Top 5

        # Extract user baseline (training profile data)
        user_baseline = ai_enrichment.get("user_baseline", {})
        user_baseline_used = (
            Json(
                {
                    "total_events": user_baseline.get("total_events", 0),
                    "baseline_strength": user_baseline.get("baseline_strength", "unknown"),
                    "apps_count": user_baseline.get("apps", {}).get("count", 0),
                    "devices_count": user_baseline.get("devices", {}).get("count", 0),
                    "locations_count": user_baseline.get("locations", {}).get("count", 0),
                    "top_apps": [app for app, _ in user_baseline.get("apps", {}).get("most_common", [])[:5]],
                    "top_devices": [dev for dev, _ in user_baseline.get("devices", {}).get("most_common", [])[:3]],
                    "top_locations": [loc for loc, _ in user_baseline.get("locations", {}).get("most_common", [])[:5]],
                }
            )
            if user_baseline
            else Json({})
        )
        # NOTE: Persisted to database after migration 003_add_user_baseline_to_llm_explanations.sql

        # Extract graph context (Neo4j historical anomaly patterns)
        graph_context = ai_enrichment.get("graph_context", {})
        graph_insights_used = (
            Json(
                {
                    "related_anomalies_count": graph_context.get("related_anomalies_count", 0),
                    "recent_detections": graph_context.get("recent_detections", 0),
                    "detected_applications": graph_context.get("detected_applications", [])[:5],
                    "detected_devices": graph_context.get("detected_devices", [])[:3],
                    "detected_locations": graph_context.get("detected_locations", [])[:5],
                    "detected_browsers": graph_context.get("detected_browsers", [])[:3],
                    "detected_operating_systems": graph_context.get("detected_operating_systems", [])[:3],
                    "detected_ips": graph_context.get("detected_ips", [])[:5],
                }
            )
            if graph_context
            else Json({})
        )

        # Quality indicators
        has_reasoning = bool(reasoning_process and len(reasoning_process) > 50)
        has_citations = bool(evidence_used and len(evidence_used) > 0)
        grounding_score = _calculate_grounding_score(explanation, rag_metadata)
        hallucination_risk = _assess_hallucination_risk(grounding_score, cold_start)

        # Version management (increment if explanation already exists)
        cursor.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1
            FROM llm_explanations
            WHERE detection_id = %s AND explanation_type = %s
            """,
            (str(detection_id), explanation_type),
        )
        result = cursor.fetchone()
        version = result[0] if result else 1

        # Insert explanation
        insert_query = """
            INSERT INTO llm_explanations (
                detection_id,
                version,
                explanation_type,
                context_analysis,
                pattern_analysis,
                anomaly_classification,
                risk_assessment,
                recommendations,
                confidence_score,
                severity_level,
                reasoning_process,
                evidence_summary,
                entities_referenced,
                similar_cases_cited,
                user_baseline_used,
                graph_insights_used,
                model_name,
                model_version,
                temperature,
                max_tokens,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cost_usd,
                latency_ms,
                has_reasoning,
                has_citations,
                grounding_score,
                hallucination_risk,
                rag_context_size,
                similar_detections_count,
                entities_count,
                cold_start,
                created_at,
                updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, NOW(), NOW()
            )
            RETURNING id
        """

        cursor.execute(
            insert_query,
            (
                str(detection_id),
                version,
                explanation_type,
                context_analysis,
                pattern_analysis,
                anomaly_classification,
                risk_assessment,
                recommendations,
                confidence_score,
                severity_level,
                reasoning_process,
                evidence_summary,
                entities_referenced,
                similar_cases_cited,
                user_baseline_used,
                graph_insights_used,
                model_name,
                None,  # model_version (not tracked yet)
                temperature,
                max_tokens,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cost_usd,
                latency_ms,
                has_reasoning,
                has_citations,
                grounding_score,
                hallucination_risk,
                rag_context_size,
                similar_detections_count,
                entities_count,
                cold_start,
            ),
        )

        result = cursor.fetchone()
        if not result:
            raise ValueError(f"Failed to insert LLM explanation for detection {detection_id}")

        explanation_id = result[0]
        conn.commit()

        logger.info(
            f"Saved LLM explanation {explanation_id} (detection: {detection_id}, "
            f"version: {version}, type: {explanation_type})"
        )

        return explanation_id

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to save LLM explanation: {e}")
        raise

    finally:
        cursor.close()


def _calculate_grounding_score(explanation: dict[str, Any], rag_metadata: dict[str, Any]) -> float:
    """
    Calculate how well the explanation is grounded in provided data.

    Scoring factors:
    - Has evidence cited (+0.3)
    - Has reasoning process (+0.2)
    - Not cold start (+0.2)
    - High RAG confidence (+0.3 * confidence)

    Returns:
        float: Score between 0.0 and 1.0
    """
    score = 0.0

    # Evidence cited
    if explanation.get("evidence_used") and len(explanation["evidence_used"]) > 0:
        score += 0.3

    # Reasoning process provided
    if explanation.get("reasoning_process") and len(explanation["reasoning_process"]) > 50:
        score += 0.2

    # Not cold start
    if not rag_metadata.get("cold_start", True):
        score += 0.2

    # RAG confidence
    rag_confidence = rag_metadata.get("confidence", 0.0)
    score += 0.3 * rag_confidence

    return min(score, 1.0)


def _assess_hallucination_risk(grounding_score: float, cold_start: bool) -> str:
    """
    Assess risk of hallucination based on grounding score.

    Args:
        grounding_score: How well grounded in data (0.0-1.0)
        cold_start: Whether RAG had insufficient data

    Returns:
        str: "LOW", "MEDIUM", or "HIGH"
    """
    if cold_start:
        return "HIGH"  # No historical context = high risk

    if grounding_score >= 0.7:
        return "LOW"
    elif grounding_score >= 0.4:
        return "MEDIUM"
    else:
        return "HIGH"


def batch_save_explanations(
    conn: psycopg2.extensions.connection,
    explanations: list[tuple[UUID | str, dict[str, Any], dict[str, Any]]],
) -> list[int]:
    """
    Save multiple LLM explanations in batch.

    Args:
        conn: PostgreSQL connection
        explanations: List of (detection_id, explanation, enriched_detection) tuples

    Returns:
        list[int]: IDs of inserted records
    """
    ids = []
    for detection_id, explanation, enriched_detection in explanations:
        try:
            exp_id = save_llm_explanation(conn, detection_id, explanation, enriched_detection)
            ids.append(exp_id)
        except Exception as e:
            logger.error(f"Failed to save explanation for detection {detection_id}: {e}")
            ids.append(None)

    logger.info(f"Batch saved {len([i for i in ids if i])} / {len(ids)} explanations")
    return ids
