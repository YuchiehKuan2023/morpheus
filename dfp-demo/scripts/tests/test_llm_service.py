#!/usr/bin/env python3
"""
Test Script: LLM Service End-to-End Validation

Tests the complete LLM generation pipeline:
1. Load enriched detections from PostgreSQL
2. Generate explanations using LLM service
3. Validate response quality and performance
4. Display metrics and sample outputs

Usage:
    # Test with 5 detections (default)
    python scripts/tests/test_llm_service.py

    # Test with specific number
    python scripts/tests/test_llm_service.py --limit 10

    # Save outputs
    python scripts/tests/test_llm_service.py --output data/output/llm_explanations.jsonl

Example Output:
    Testing LLM Service...
    Model: openai/gpt-oss-120b

    Generated 5 explanations

    EXPLANATION 1/5
    ================================================================================
    ## Context
    User melissa.mitchell accessed HubSpot from UNKNOWN-LAPTOP-999...

    ## Pattern
    First-time device access with 3 similar anomalies in 24h window...

    ## Risk: HIGH
    Potential credential compromise with data exfiltration risk...

    ## Recommendations
    1. Revoke active session immediately
    2. Force MFA re-authentication
    3. Review recent HubSpot data access logs

    Model: openai/gpt-oss-120b
    Tokens: 482 (prompt: 312, completion: 170)
    Latency: 1.2s
    Cost: $0.0005

    ================================================================================
    METRICS
    ================================================================================
    Total requests: 5
    Total tokens: 2,410
    Total cost: $0.0025
    Avg latency: 1.1s
    Error rate: 0.0%

Author: AI Intelligence Layer Team
Date: 2026-02-20
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Add modules to path
sys.path.append(str(Path(__file__).parent.parent.parent))

import psycopg2
from dotenv import load_dotenv

from modules.ai.llm.llm_service import LLMService

# Load environment variables
load_dotenv()


def load_enriched_detections_from_postgres(limit: int = 5) -> list[dict[str, Any]]:
    """
    Load enriched detections from PostgreSQL database.

    Args:
        limit: Number of detections to load

    Returns:
        List of enriched detection dicts
    """
    # Connect to PostgreSQL
    from modules.utils.db import get_db_params

    conn = psycopg2.connect(**get_db_params())

    cursor = conn.cursor()

    # Query enriched_anomalies table
    query = """
        SELECT
            user_id,
            timestamp,
            anomaly_score,
            mean_abs_z,
            original_event,
            ai_enrichment,
            raw_detection
        FROM enriched_anomalies
        ORDER BY timestamp DESC
        LIMIT %s
    """

    cursor.execute(query, (limit,))
    rows = cursor.fetchall()

    # Build enriched detection dicts
    enriched_detections = []
    for row in rows:
        enriched = {
            "user_id": row[0],
            "timestamp": row[1].isoformat() if hasattr(row[1], "isoformat") else row[1],
            "anomaly_score": float(row[2]),
            "mean_abs_z": float(row[3]),
            "original_event": row[4],  # JSONB
            "ai_enrichment": row[5],  # JSONB
            "raw_detection": row[6],  # JSONB
        }
        enriched_detections.append(enriched)

    cursor.close()
    conn.close()

    return enriched_detections


def print_explanation(
    explanation: dict[str, Any], index: int, total: int, verbose: bool = True, json_output: bool = False
):
    """Print formatted explanation with structured analysis fields or full JSON."""
    print(f"\n{'=' * 80}")
    print(f"EXPLANATION {index}/{total}")
    print("=" * 80)

    # If JSON output requested, print full JSON and return
    if json_output:
        print(json.dumps(explanation, indent=2))
        return

    # Print classification header
    classification = explanation.get("anomaly_classification", "unknown").upper()
    confidence = explanation.get("confidence_score", 0.0)
    severity = explanation.get("severity_level", "UNKNOWN")

    print(f"\nClassification: {classification} | Confidence: {confidence:.1%} | Severity: {severity}\n")

    # Print structured analysis
    if explanation.get("context_analysis"):
        print("CONTEXT ANALYSIS")
        print("-" * 80)
        print(explanation["context_analysis"])

    if explanation.get("pattern_analysis"):
        print("\nPATTERN ANALYSIS")
        print("-" * 80)
        print(explanation["pattern_analysis"])

    if explanation.get("risk_assessment"):
        print("\nRISK ASSESSMENT")
        print("-" * 80)
        print(explanation["risk_assessment"])

    if explanation.get("recommendations"):
        print("\nRECOMMENDATIONS")
        print("-" * 80)
        print(explanation["recommendations"])

    # Print evidence if verbose
    if verbose:
        if explanation.get("evidence_used"):
            print("\nEVIDENCE CITED")
            print("-" * 80)
            for evidence in explanation["evidence_used"]:
                print(f"  • {evidence}")

        if explanation.get("reasoning_process"):
            print("\nREASONING PROCESS")
            print("-" * 80)
            print(explanation["reasoning_process"])

        # Print performance metadata
        print("\nPERFORMANCE")
        print("-" * 80)
        print(f"Model: {explanation.get('model_name', 'N/A')}")
        performance = explanation.get("performance", {})
        print(
            f"Tokens: {performance.get('tokens_used', 0)} "
            f"(prompt: {performance.get('prompt_tokens', 0)}, "
            f"completion: {performance.get('completion_tokens', 0)})"
        )
        print(f"Latency: {performance.get('latency_ms', 0) / 1000:.1f}s")
        print(f"Cost: ${performance.get('cost_usd', 0):.4f}")

        # Print model reasoning if available (from Groq's reasoning models)
        if "model_reasoning" in explanation and explanation["model_reasoning"]:
            print("\nMODEL REASONING (Internal)")
            print("-" * 80)
            print(explanation["model_reasoning"])


def print_metrics(metrics: dict[str, Any]):
    """Print service metrics summary."""
    print(f"\n{'=' * 80}")
    print("METRICS SUMMARY")
    print("=" * 80)
    print(f"Total requests: {metrics['total_requests']}")
    print(f"Total tokens: {metrics['total_tokens']:,}")
    print(f"Total cost: ${metrics['total_cost_usd']:.4f}")
    print(f"Avg latency: {metrics['avg_latency_ms'] / 1000:.1f}s")


def print_classification_summary(explanations: list[dict[str, Any]], metrics: dict[str, Any]):
    """Print classification breakdown and statistics."""
    print(f"\n{'=' * 80}")
    print("CLASSIFICATION BREAKDOWN")
    print("=" * 80)

    # Count classifications
    true_positives = [e for e in explanations if e.get("anomaly_classification") == "true_positive"]
    false_positives = [e for e in explanations if e.get("anomaly_classification") == "false_positive"]
    uncertain = [e for e in explanations if e.get("anomaly_classification") == "uncertain"]

    total = len(explanations)

    print(f"\nTrue Positives:  {len(true_positives):3d} ({len(true_positives) / total * 100:5.1f}%)")
    print(f"False Positives: {len(false_positives):3d} ({len(false_positives) / total * 100:5.1f}%)")
    print(f"Uncertain:       {len(uncertain):3d} ({len(uncertain) / total * 100:5.1f}%)")

    # Severity breakdown
    print("\n\nSEVERITY DISTRIBUTION")
    print("-" * 80)
    critical = len([e for e in explanations if e.get("severity_level") == "CRITICAL"])
    high = len([e for e in explanations if e.get("severity_level") == "HIGH"])
    medium = len([e for e in explanations if e.get("severity_level") == "MEDIUM"])
    low = len([e for e in explanations if e.get("severity_level") == "LOW"])

    print(f"CRITICAL: {critical:3d} ({critical / total * 100:5.1f}%)")
    print(f"HIGH:     {high:3d} ({high / total * 100:5.1f}%)")
    print(f"MEDIUM:   {medium:3d} ({medium / total * 100:5.1f}%)")
    print(f"LOW:      {low:3d} ({low / total * 100:5.1f}%)")

    # Confidence statistics
    print("\n\nCONFIDENCE STATISTICS")
    print("-" * 80)
    confidences = [e.get("confidence_score", 0.0) for e in explanations]
    if confidences:
        avg_confidence = sum(confidences) / len(confidences)
        min_confidence = min(confidences)
        max_confidence = max(confidences)

        print(f"Average: {avg_confidence:.1%}")
        print(f"Min:     {min_confidence:.1%}")
        print(f"Max:     {max_confidence:.1%}")

        # Confidence distribution
        high_conf = len([c for c in confidences if c >= 0.8])
        med_conf = len([c for c in confidences if 0.5 <= c < 0.8])
        low_conf = len([c for c in confidences if c < 0.5])

        print(f"\nHigh confidence (≥80%): {high_conf} ({high_conf / total * 100:.1f}%)")
        print(f"Med confidence (50-80%): {med_conf} ({med_conf / total * 100:.1f}%)")
        print(f"Low confidence (<50%):   {low_conf} ({low_conf / total * 100:.1f}%)")
    print(f"Error rate: {metrics['error_rate']:.1%}")

    # Cost projections
    if metrics["total_requests"] > 0:
        cost_per_explanation = metrics["total_cost_usd"] / metrics["total_requests"]
        print(f"\nCost per explanation: ${cost_per_explanation:.4f}")
        print(f"Estimated cost for 1,000 explanations: ${cost_per_explanation * 1000:.2f}")
        print(f"Estimated cost per month (30K explanations): ${cost_per_explanation * 30000:.2f}")


def save_explanations(explanations: list[dict[str, Any]], output_path: str):
    """Save explanations to JSONL file."""
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        for explanation in explanations:
            f.write(json.dumps(explanation) + "\n")

    print(f"\nSaved {len(explanations)} explanations to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Test LLM Service End-to-End",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Test with default settings (5 detections, default mode)
    python scripts/tests/test_llm_service.py

    # Test with more detections
    python scripts/tests/test_llm_service.py --limit 20

    # Save outputs to file
    python scripts/tests/test_llm_service.py --output data/output/explanations.jsonl

    # Quiet mode (only show metrics)
    python scripts/tests/test_llm_service.py --quiet
        """,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of detections to process (default: 5)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file for explanations (default: stdout only)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Quiet mode: only show metrics summary",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full JSON response instead of formatted text",
    )
    parser.add_argument(
        "--include-reasoning",
        action="store_true",
        help="Include reasoning process in output",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=2.0,
        help="Delay between requests in seconds (default: 2.0 for free tier)",
    )
    parser.add_argument(
        "--free-tier",
        action="store_true",
        help="Use free tier settings (30 RPM = 2s delay)",
    )

    args = parser.parse_args()

    # Auto-set rate limit for free tier
    if args.free_tier:
        args.rate_limit = 2.0
        print("Free tier mode: Using 2s delay between requests (30 RPM limit)")

    # Verify GROQ_API_KEY is set
    if not os.getenv("GROQ_API_KEY"):
        print("Error: GROQ_API_KEY not set in environment")
        print("Set it in .env file or export GROQ_API_KEY=your_key_here")
        sys.exit(1)

    print("\n🚀 Testing LLM Service...")
    print(f"Detections: {args.limit}")

    # Initialize LLM service
    try:
        llm = LLMService()
        print(f"Model: {llm.main_model}")
    except Exception as e:
        print(f"Failed to initialize LLM service: {e}")
        sys.exit(1)

    # Load enriched detections from PostgreSQL
    print(f"\nLoading {args.limit} enriched detections from PostgreSQL...")
    try:
        enriched_detections = load_enriched_detections_from_postgres(args.limit)
        print(f"Loaded {len(enriched_detections)} enriched detections")
    except Exception as e:
        print(f"Failed to load detections: {e}")
        print("\nMake sure:")
        print("1. PostgreSQL is running")
        print("2. enriched_anomalies table is populated")
        print("3. Database credentials are correct in .env")
        sys.exit(1)

    # Generate explanations
    print("\nGenerating explanations...")
    if args.rate_limit > 0:
        estimated_time = args.limit * args.rate_limit / 60
        print(f"Estimated time: ~{estimated_time:.1f} minutes (with {args.rate_limit}s delay)")

    try:
        explanations = []
        for i, enriched in enumerate(enriched_detections, 1):
            print(f"  Progress: {i}/{len(enriched_detections)}", end="\r")

            explanation = llm.generate_explanation(
                enriched,
                include_reasoning=args.include_reasoning,
            )
            explanations.append(explanation)

            # Rate limiting for free tier
            if i < len(enriched_detections) and args.rate_limit > 0:
                time.sleep(args.rate_limit)

        print(f"\nGenerated {len(explanations)} explanations")

    except Exception as e:
        print(f"\nFailed to generate explanations: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Display results
    if not args.quiet:
        for i, explanation in enumerate(explanations, 1):
            print_explanation(explanation, i, len(explanations), verbose=not args.quiet, json_output=args.json)

    # Get metrics
    metrics = llm.get_metrics()

    # Print classification breakdown with metrics
    print_classification_summary(explanations, metrics)

    # Print metrics
    print_metrics(metrics)

    # Save if requested
    if args.output:
        save_explanations(explanations, args.output)

    print(f"\n{'=' * 80}")
    print("LLM Service Test Complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
