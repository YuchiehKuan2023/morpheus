"""
Analyst permission constants for the DFP platform.

Defines the analyst level hierarchy and maps each level to the anomaly
severities that analysts at that level are allowed to be assigned.

Level scheme:
  1 — SOC Analyst L1  → LOW only
  2 — SOC Analyst L2  → MEDIUM only
  3 — SOC Analyst L3  → HIGH, CRITICAL
  4 — SOC Manager / Admin → ALL severities (LOW, MEDIUM, HIGH, CRITICAL)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Analyst levels
# ---------------------------------------------------------------------------

ANALYST_LEVEL_L1 = 1
ANALYST_LEVEL_L2 = 2
ANALYST_LEVEL_L3 = 3
ANALYST_LEVEL_ADMIN = 4

ANALYST_LEVELS: dict[int, dict[str, str | list[str]]] = {
    ANALYST_LEVEL_L1: {
        "label": "SOC Analyst L1",
        "description": "Junior analyst — triages low-severity anomalies",
        "allowed_severities": ["LOW"],
    },
    ANALYST_LEVEL_L2: {
        "label": "SOC Analyst L2",
        "description": "Mid-level analyst — investigates medium-severity anomalies",
        "allowed_severities": ["MEDIUM"],
    },
    ANALYST_LEVEL_L3: {
        "label": "SOC Analyst L3",
        "description": "Senior analyst — handles high and critical anomalies",
        "allowed_severities": ["HIGH", "CRITICAL"],
    },
    ANALYST_LEVEL_ADMIN: {
        "label": "SOC Manager / Admin",
        "description": "Full access — can review any anomaly regardless of severity",
        "allowed_severities": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    },
}

# All valid severity values (ordered by priority, lowest first)
ALL_SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# ---------------------------------------------------------------------------
# Roles that grant admin-level (level 4) permissions
# ---------------------------------------------------------------------------

ADMIN_ROLES = {"soc_manager", "compliance_officer"}


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


def get_allowed_severities(level: int) -> list[str]:
    """Return the list of anomaly severities an analyst at *level* may handle."""
    entry = ANALYST_LEVELS.get(level)
    if entry is None:
        return []
    return list(entry["allowed_severities"])


def can_handle_severity(level: int, severity: str) -> bool:
    """Return ``True`` if an analyst at *level* is allowed to handle *severity*."""
    return severity.upper() in get_allowed_severities(level)


def severity_to_min_level(severity: str) -> int:
    """Return the minimum analyst level required to handle *severity*."""
    sev = severity.upper()
    for level, entry in ANALYST_LEVELS.items():
        if sev in entry["allowed_severities"]:
            return level
    return ANALYST_LEVEL_ADMIN  # fallback — require admin for unknown severities
