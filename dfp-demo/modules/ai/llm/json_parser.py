"""
Deprecated: json_parser has moved to modules/ai/shared/json_parser.

This shim re-exports everything from the new location for backward compatibility.
Update your imports to: from modules.ai.shared.json_parser import ...
"""

from modules.ai.shared.json_parser import (
    JSON_REPAIR_AVAILABLE,
    extract_json_from_markdown,
    extract_partial_json,
    fix_common_json_errors,
    get_default_explanation_structure,
    parse_llm_json,
    validate_llm_response_structure,
)

# Explicit re-export declaration — tells linters and readers these imports are
# intentional public symbols, not unused imports.
__all__ = [
    "JSON_REPAIR_AVAILABLE",
    "extract_json_from_markdown",
    "extract_partial_json",
    "fix_common_json_errors",
    "get_default_explanation_structure",
    "parse_llm_json",
    "validate_llm_response_structure",
]
