#!/usr/bin/env python3
"""
Robust JSON Parser for LLM Responses

Handles malformed JSON from LLM outputs with multiple fallback strategies:
1. Standard json.loads()
2. Extract from markdown code blocks
3. json-repair library for sophisticated fixing (recommended)
4. Manual regex fixes for common errors (fallback with limitations)
5. Partial JSON extraction for incomplete responses

Strategy priority optimized to use json-repair (when available) before manual
fixes, as json-repair is more sophisticated and avoids issues like breaking
apostrophes in string content.

Moved from modules/ai/llm/json_parser.py — shared utility used across
multiple AI modules (llm, auto_labeling, etc.).

Author: AI Intelligence Layer Team
Date: 2026-02-20
"""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Try to import json-repair for robust fixing
try:
    from json_repair import repair_json

    JSON_REPAIR_AVAILABLE = True
except ImportError:
    JSON_REPAIR_AVAILABLE = False
    repair_json = None  # type: ignore[assignment]
    logger.warning("json-repair not installed. Using fallback JSON parsing. Install with: pip install json-repair")


def parse_llm_json(raw_response: str, fallback_structure: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Parse JSON from LLM response with multiple fallback strategies.

    Strategy order (optimized for reliability):
    1. Direct json.loads() - Try standard JSON parsing
    2. Extract from markdown code blocks - Handle ```json...``` wrappers
    3. json-repair library - Sophisticated fixing for malformed JSON
    4. Manual regex fixes - Fallback when json-repair unavailable (has limitations)
    5. Partial extraction - Best effort for incomplete responses

    Args:
        raw_response: Raw text response from LLM
        fallback_structure: Default structure to return if all parsing fails

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If all parsing strategies fail and no fallback provided
    """
    if not raw_response or not raw_response.strip():
        if fallback_structure:
            return fallback_structure
        raise ValueError("Empty response from LLM")

    # Strategy 1: Direct JSON parsing
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError:
        logger.debug("Direct JSON parsing failed, trying extraction strategies...")

    # Strategy 2: Extract from markdown code blocks
    extracted = extract_json_from_markdown(raw_response)
    if extracted:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            logger.debug("Markdown extraction failed, trying json-repair...")

    # Strategy 3: Use json-repair library (if available)
    # json-repair is more sophisticated than manual fixes and should be tried first
    if JSON_REPAIR_AVAILABLE and repair_json is not None:
        try:
            repaired = repair_json(extracted or raw_response)
            return json.loads(repaired)
        except Exception as e:
            logger.debug(f"json-repair failed: {e}, trying manual fixes as fallback...")

    # Strategy 4: Manual fixes for common issues (fallback when json-repair unavailable)
    # Note: These fixes have limitations (e.g., may break apostrophes in content)
    fixed = fix_common_json_errors(extracted or raw_response)
    if fixed:
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            logger.debug(f"Manual fixes failed, trying partial extraction... Error: {e}")

    # Strategy 5: Extract partial JSON (best effort)
    # This attempts to salvage what we can from incomplete responses
    partial = extract_partial_json(raw_response)
    if partial:
        try:
            return json.loads(partial)
        except json.JSONDecodeError as e:
            logger.debug(f"Partial JSON parsing failed: {e}")

    # All strategies failed
    logger.error(f"All JSON parsing strategies failed. Raw response:\n{raw_response[:500]}...")

    if fallback_structure:
        logger.warning("Returning fallback structure")
        return fallback_structure

    raise ValueError("Failed to parse JSON from LLM response after all strategies")


def extract_json_from_markdown(text: str) -> str | None:
    """Extract JSON from markdown code blocks."""
    # Pattern 1: ```json ... ```
    json_block_pattern = r"```json\s*\n(.*?)\n```"
    match = re.search(json_block_pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Pattern 2: ``` ... ``` (generic code block)
    generic_block_pattern = r"```\s*\n(.*?)\n```"
    match = re.search(generic_block_pattern, text, re.DOTALL)
    if match:
        content = match.group(1).strip()
        # Check if it looks like JSON
        if content.startswith("{") or content.startswith("["):
            return content

    # Pattern 3: Find the outermost JSON object by brace-matching
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

    return None


def fix_common_json_errors(text: str) -> str | None:
    """Fix common JSON formatting errors.

    WARNING: This function has known limitations:
    - Single quote replacement may break apostrophes in content
      (e.g., "user's device" becomes "user"s device")
    - Use json-repair library when available for more robust fixing
    - This function should only be used as a fallback
    """
    if not text:
        return None

    try:
        # Remove comments (// and /* */)
        text = re.sub(r"//.*?\n", "\n", text)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

        # Fix trailing commas before } or ]
        text = re.sub(r",(\s*[}\]])", r"\1", text)

        # Fix single quotes to double quotes
        # LIMITATION: This may break apostrophes within string content
        # Example: {'name': "user's device"} -> {"name": "user"s device"} (invalid!)
        # Only replace single quotes that are likely JSON string delimiters
        # Better solution: use json-repair library which handles this correctly
        text = re.sub(r"(?<=[{\[,:])\s*'([^']*?)'\s*(?=[,}\]:])", r'"\1"', text)

        # Fix unquoted keys
        text = re.sub(r"(?<={|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r' "\1":', text)

        # Fix missing commas between key-value pairs
        text = re.sub(r'"\s*\n\s*"', '",\n"', text)

        # Remove trailing commas at end
        text = re.sub(r",\s*$", "", text)

        return text.strip()

    except Exception as e:
        logger.warning(f"Error during manual JSON fixing: {e}")
        return None


def extract_partial_json(text: str) -> str | None:
    """
    Extract valid JSON even if response is incomplete.

    Tries to find the largest valid JSON structure in the text.
    """
    # Find potential JSON start
    json_start = text.find("{")
    if json_start == -1:
        return None

    # Try progressively shorter substrings from the start
    for end_pos in range(len(text), json_start, -1):
        candidate = text[json_start:end_pos].strip()

        # Try to balance braces
        if candidate.count("{") > candidate.count("}"):
            # Add missing closing braces
            missing_braces = candidate.count("{") - candidate.count("}")
            candidate = candidate + "}" * missing_braces

        try:
            # Validate it's valid JSON
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue

    return None


def validate_llm_response_structure(
    parsed: dict[str, Any], required_fields: list[str], field_types: dict[str, type | tuple[type, ...]] | None = None
) -> tuple[bool, list[str]]:
    """
    Validate parsed JSON has required structure.

    Args:
        parsed: Parsed JSON dict
        required_fields: List of required field names
        field_types: Optional dict mapping field names to expected types (can be tuple of types)

    Returns:
        (is_valid, missing_or_invalid_fields)
    """
    errors = []

    # Check required fields
    for field in required_fields:
        if field not in parsed:
            errors.append(f"Missing required field: {field}")
            continue

        # Check types if specified
        if field_types and field in field_types:
            expected_type = field_types[field]
            actual_value = parsed[field]

            # Handle both single type and tuple of types
            if not isinstance(actual_value, expected_type):
                errors.append(f"Field '{field}' has wrong type: expected {expected_type}, got {type(actual_value)}")

    is_valid = len(errors) == 0
    return is_valid, errors


def get_default_explanation_structure() -> dict[str, Any]:
    """
    Get default structure for explanation responses.

    Used as fallback when JSON parsing completely fails.
    """
    return {
        "context_analysis": "[Parsing error - unable to extract context]",
        "pattern_analysis": "[Parsing error - unable to extract pattern]",
        "anomaly_classification": {"positive": None, "threat_types": None},
        "risk_assessment": "[Parsing error - unable to extract risk]",
        "recommendations": "Manual review required - LLM response could not be parsed",
        "confidence_score": 0.0,
        "severity_level": "MEDIUM",
        "evidence_used": ["[Parsing error]"],
        "reasoning_process": "Response parsing failed - unable to extract reasoning",
        "_parsing_error": True,
    }


# Example usage
if __name__ == "__main__":
    # Test cases
    test_cases = [
        # Valid JSON
        '{"anomaly_classification": "true_positive", "confidence_score": 0.85}',
        # JSON in markdown
        '```json\n{"anomaly_classification": "false_positive", "confidence_score": 0.92}\n```',
        # Trailing comma
        '{"anomaly_classification": "uncertain", "confidence_score": 0.5,}',
        # Single quotes
        "{'anomaly_classification': 'true_positive', 'confidence_score': 0.88}",
        # Unquoted keys
        "{anomaly_classification: 'uncertain', confidence_score: 0.6}",
        # Incomplete JSON
        '{"anomaly_classification": "true_positive", "confidence_score": 0.75, "evidence_used": ["entity: UNKNOWN-DEVICE"',
    ]

    for i, test_input in enumerate(test_cases, 1):
        print(f"\n{'=' * 60}")
        print(f"Test {i}")
        print(f"{'=' * 60}")
        print(f"Input: {test_input[:100]}...")

        try:
            result = parse_llm_json(test_input, fallback_structure=get_default_explanation_structure())
            print("✅ Parsed successfully:")
            print(json.dumps(result, indent=2))
        except Exception as e:
            print(f"❌ Failed: {e}")
