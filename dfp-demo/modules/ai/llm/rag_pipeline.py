#!/usr/bin/env python3
"""
RAG Pipeline: Context Assembly for LLM Generation

Assembles Retrieval-Augmented Generation (RAG) context from enriched detections.
Combines entity extraction, similarity search, and graph queries into structured
context that enhances LLM explanations with specific, relevant information.

Architecture:
    Input: EnrichedDetection (with ai_enrichment metadata)
    Processing:
        1. Extract entities (apps, devices, IPs, locations)
        2. Format similar detections (historical context)
        3. Format graph relationships (user patterns)
        4. Determine anomaly type classification
        5. Assemble into structured context dict
    Output: RAG Context for LLM prompt

Context Sources (from EnrichedDetection):
    - entities: WHO/WHAT/WHERE (from original_event + detection)
    - similar_detections: Historical patterns from Qdrant
    - graph_context: Entity relationships from Neo4j
    - original_event: Full Azure AD sign-in event
    - raw_detection: DFP anomaly scores and features

Operations:
    - assemble_context: Build complete RAG context
    - classify_anomaly_type: Determine anomaly category
    - prioritize_entities: Rank entities by relevance
    - format_context: Structure for LLM consumption

Context Structure:
    {
        "anomaly_type": str,  # Classification (e.g., "Unknown Device Access")
        "entities": [...]  # Extracted entities with metadata
        "similar_detections": [...]  # Top K similar cases
        "graph_context": {...}  # User patterns and relationships
        "metadata": {...}  # Cold start status, confidence scores
    }

Reference:
    modules/ai/llm/llm_service.py (LLM generation)
    modules/ai/enrichment/enrichment_service.py (Enrichment source)

Author: AI Intelligence Layer Team
Date: 2026-02-20
"""

import logging
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class RAGPipeline:
    """
    Assemble RAG context from enriched detections.

    Structures all enrichment data (entities, similar cases, graph context)
    into optimized context for LLM generation.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize RAG pipeline.

        Args:
            config: RAG configuration from llm.yaml (rag section)
        """
        self.config = config or {}

        # Context source weights (for prioritization)
        sources = self.config.get("sources", {})
        self.weights = {
            "similar_detections": sources.get("similar_detections", {}).get("weight", 0.4),
            "graph_context": sources.get("graph_context", {}).get("weight", 0.3),
            "entities": sources.get("entities", {}).get("weight", 0.2),
        }

        # Max context tokens
        self.max_context_tokens = self.config.get("context", {}).get("max_tokens", 4000)

        logger.info("✅ RAG Pipeline initialized")

    def assemble_context(self, enriched_detection: dict[str, Any]) -> dict[str, Any]:
        """
        Assemble complete RAG context from enriched detection.

        Args:
            enriched_detection: Enriched detection from enrichment_service

        Returns:
            RAG context dict with:
                {
                    "anomaly_type": str,
                    "entities": list[dict],
                    "similar_detections": list[dict],
                    "graph_context": dict,
                    "metadata": {
                        "cold_start": bool,
                        "confidence": float,
                        "context_size_estimate": int
                    }
                }
        """
        ai_enrichment = enriched_detection.get("ai_enrichment", {})
        original_event = enriched_detection.get("original_event", {})

        # 1. Classify anomaly type
        anomaly_type = self._classify_anomaly_type(enriched_detection, ai_enrichment, original_event)

        # 2. Extract and prioritize entities
        entities = self._prioritize_entities(ai_enrichment.get("entities", []), anomaly_type)

        # 3. Format similar detections
        similar_detections = self._format_similar_detections(ai_enrichment.get("similar_detections", []))

        # 4. Extract user baseline (training profile)
        user_baseline = ai_enrichment.get("user_baseline", {})

        # 5. Format graph context (Neo4j historical anomaly patterns)
        graph_context = self._format_graph_context(ai_enrichment.get("graph_context", {}))

        # 6. Calculate metadata
        metadata = {
            "cold_start": ai_enrichment.get("cold_start", False),
            "confidence": self._calculate_confidence(ai_enrichment),
            "context_size_estimate": self._estimate_context_size(entities, similar_detections, graph_context),
        }

        context = {
            "anomaly_type": anomaly_type,
            "entities": entities,
            "user_baseline": user_baseline,
            "similar_detections": similar_detections,
            "graph_context": graph_context,
            "metadata": metadata,
        }

        logger.debug(
            f"Assembled RAG context: {anomaly_type}, "
            f"{len(entities)} entities, "
            f"{len(similar_detections)} similar cases, "
            f"~{metadata['context_size_estimate']} tokens"
        )

        return context

    def _classify_anomaly_type(
        self,
        enriched_detection: dict[str, Any],
        ai_enrichment: dict[str, Any],
        original_event: dict[str, Any],
    ) -> str:
        """
        Classify anomaly into specific type based on enrichment data.

        Anomaly Types:
            - Unknown Device Access
            - Unusual Application Access
            - Geographic Anomaly
            - Time-based Anomaly
            - Behavioral Anomaly
            - Multiple Related Anomalies
        """
        entities = ai_enrichment.get("entities", [])
        similar_count = len(ai_enrichment.get("similar_detections", []))
        anomaly_score = enriched_detection.get("anomaly_score", 0)

        # Extract entity types
        entity_types = {e["type"].lower() for e in entities}

        # Check for unknown device
        if "device" in entity_types:
            device_entities = [e for e in entities if e["type"].lower() == "device"]
            for device in device_entities:
                if "unknown" in device.get("text", "").lower():
                    return "Unknown Device Access"

        # Check for application anomaly
        if "application" in entity_types:
            app_entities = [e for e in entities if e["type"].lower() == "application"]
            # Check if high-risk app or unusual app
            if app_entities and anomaly_score > 10:
                return "Unusual Application Access"

        # Check for location anomaly
        if "location" in entity_types:
            location_entities = [e for e in entities if e["type"].lower() == "location"]
            if location_entities and similar_count < 2:
                return "Geographic Anomaly"

        # Check for multiple related anomalies (pattern)
        if similar_count >= 3:
            return "Multiple Related Anomalies"

        # Check for high severity
        if anomaly_score > 15:
            return "Critical Behavioral Anomaly"

        # Default: General behavioral anomaly
        return "Behavioral Anomaly"

    def _prioritize_entities(self, entities: list[dict[str, Any]], anomaly_type: str) -> list[dict[str, Any]]:
        """
        Prioritize entities based on relevance to anomaly type.

        Priority:
            - Unknown Device Access: device > location > application
            - Unusual Application Access: application > device > location
            - Geographic Anomaly: location > ip_address > device
            - Default: confidence score
        """
        if not entities:
            return []

        # Copy entities to avoid mutation
        prioritized = entities.copy()

        # Define priority weights by anomaly type
        priority_weights = {
            "Unknown Device Access": {"device": 3, "location": 2, "application": 1},
            "Unusual Application Access": {
                "application": 3,
                "device": 2,
                "location": 1,
            },
            "Geographic Anomaly": {"location": 3, "ip_address": 2, "device": 1},
        }

        weights = priority_weights.get(anomaly_type, {})

        # Sort by priority weight, then confidence
        def sort_key(entity):
            entity_type = entity.get("type", "").lower()
            type_weight = weights.get(entity_type, 0)
            confidence = entity.get("confidence", 0)
            return (type_weight, confidence)

        prioritized.sort(key=sort_key, reverse=True)

        return prioritized

    def _format_similar_detections(self, similar_detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Format similar detections for RAG context.

        Adds derived fields:
            - time_diff: Time since similar detection
            - relevance_score: Weighted combination of similarity + recency
        """
        if not similar_detections:
            return []

        formatted = []
        for sim in similar_detections:
            # Calculate relevance (similarity is already 0-1)
            similarity = sim.get("similarity_score", 0)
            relevance = similarity  # Can add time decay later

            formatted.append(
                {
                    "detection_id": sim.get("detection_id", "unknown"),
                    "user_id": sim.get("user_id", "unknown"),
                    "timestamp": sim.get("timestamp", ""),
                    "similarity_score": similarity,
                    "anomaly_score": sim.get("anomaly_score", 0),
                    "relevance_score": relevance,
                }
            )

        # Sort by relevance (highest first)
        formatted.sort(key=lambda x: x["relevance_score"], reverse=True)

        return formatted

    def _format_graph_context(self, graph_context: dict[str, Any]) -> dict[str, Any]:
        """
        Format graph context for RAG.

        Extracts key patterns:
            - user_applications: Apps user typically accesses
            - user_devices: Devices user typically uses
            - user_locations: Locations user typically accesses from
            - related_anomalies_count: Count of related anomalies
        """
        if not graph_context:
            return {}

        # Graph context is already structured from enrichment_service
        # Just ensure consistent format
        return {
            "user_applications": graph_context.get("user_applications", []),
            "user_devices": graph_context.get("user_devices", []),
            "user_locations": graph_context.get("user_locations", []),
            "related_anomalies_count": graph_context.get("related_anomalies_count", 0),
            "user_activity_count": graph_context.get("user_activity_count", 0),
        }

    def _calculate_confidence(self, ai_enrichment: dict[str, Any]) -> float:
        """
        Calculate overall confidence score for enrichment.

        Factors:
            - Has entities: +0.3
            - Has embedding: +0.2
            - Has similar detections (!cold_start): +0.3
            - Has graph context: +0.2
        """
        confidence = 0.0

        if ai_enrichment.get("entities"):
            confidence += 0.3

        if ai_enrichment.get("embedding"):
            confidence += 0.2

        if ai_enrichment.get("similar_detections") and not ai_enrichment.get("cold_start", False):
            confidence += 0.3

        if ai_enrichment.get("graph_context"):
            confidence += 0.2

        return min(confidence, 1.0)  # Cap at 1.0

    def _estimate_context_size(
        self,
        entities: list[dict[str, Any]],
        similar_detections: list[dict[str, Any]],
        graph_context: dict[str, Any],
    ) -> int:
        """
        Estimate context size in tokens (rough approximation).

        Approximations:
            - Each entity: ~50 tokens
            - Each similar detection: ~80 tokens
            - Graph context: ~200 tokens
            - Base prompt template: ~300 tokens
        """
        size = 300  # Base template

        # Entities
        size += len(entities) * 50

        # Similar detections
        size += len(similar_detections) * 80

        # Graph context
        if graph_context:
            size += 200

        return size


# CLI for testing
if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python rag_pipeline.py <enriched_detection.json>")
        sys.exit(1)

    # Load enriched detection
    with open(sys.argv[1]) as f:
        enriched_detection = json.load(f)

    # Initialize RAG pipeline
    rag = RAGPipeline()

    # Assemble context
    context = rag.assemble_context(enriched_detection)

    # Print results
    print("\n" + "=" * 80)
    print("RAG CONTEXT")
    print("=" * 80)
    print(json.dumps(context, indent=2))
    print("\n" + "=" * 80)
    print("METADATA")
    print("=" * 80)
    print(f"Anomaly Type: {context['anomaly_type']}")
    print(f"Entities: {len(context['entities'])}")
    print(f"Similar Cases: {len(context['similar_detections'])}")
    print(f"Confidence: {context['metadata']['confidence']:.2f}")
    print(f"Context Size: ~{context['metadata']['context_size_estimate']} tokens")
    print(f"Cold Start: {context['metadata']['cold_start']}")
