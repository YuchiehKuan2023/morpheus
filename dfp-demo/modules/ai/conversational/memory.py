"""
Working Memory — scratchpad for the ReAct agent's reasoning loop.

Tracks thoughts, tool invocations, observations, entities mentioned,
and token budgets across the steps of a single turn.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Human-readable tool labels (mirrors frontend TOOL_LABELS)
TOOL_LABELS: dict[str, str] = {
    "search_anomalies": "Anomaly Search",
    "get_anomaly_detail": "Anomaly Detail",
    "get_user_profile": "User Profile",
    "get_similar_anomalies": "Similarity Search",
    "get_risk_summary": "Risk Summary",
    "get_top_anomalies": "Top Anomalies",
    "get_investigation": "Investigation Findings",
    "get_neo4j_graph": "Knowledge Graph",
    "get_root_cause_summary": "Root Cause Analysis",
    "semantic_search_anomalies": "Semantic Search",
    "get_anomaly_timeline": "Timeline",
    "get_user_behaviour_baseline": "User Baseline",
    "get_llm_explanations": "AI Explanations",
    "get_dimension_ranking": "Dimension Ranking",
    "query_database": "Custom Query",
}


@dataclass(slots=True)
class Observation:
    """A single tool result recorded in working memory."""

    tool_name: str
    params: dict[str, Any]
    data: Any
    tokens: int
    success: bool
    error: str | None = None

    @property
    def label(self) -> str:
        """Human-readable tool label."""
        return TOOL_LABELS.get(self.tool_name, self.tool_name)

    def summary_line(self) -> str:
        """One-line human-readable summary of the tool result."""
        if not self.success:
            return f"{self.label}: FAILED — {self.error}"

        data = self.data
        if not isinstance(data, dict):
            return f"{self.label}: result retrieved"

        # --- Tool-specific readable summaries ---

        if self.tool_name == "get_user_profile":
            if "error" in data:
                return f"{self.label}: {data['error']}"
            user = data.get("user", {})
            stats = data.get("anomaly_stats", {})
            if isinstance(user, str):
                name = user
            else:
                name = user.get("display_name") or user.get("username") or "Unknown"
            total = stats.get("total_anomalies", 0)
            max_risk = stats.get("max_risk_score", "N/A")
            return f"Retrieved profile for {name}: {total} anomalies, max risk score {max_risk}"

        if self.tool_name == "get_user_behaviour_baseline":
            baselines = data.get("baselines", [])
            if not baselines:
                return f"No baseline data found{self._param_hint('username')}"
            b = baselines[0]
            name = b.get("display_name") or b.get("username") or "Unknown"
            city = b.get("primary_location_city", "")
            dept = b.get("department", "")
            parts = [f"Retrieved baseline for {name}"]
            if dept:
                parts.append(dept)
            if city:
                parts.append(city)
            return " — ".join(parts)

        if self.tool_name in ("search_anomalies", "semantic_search_anomalies"):
            total = data.get("total_matching", 0)
            returned = data.get("returned", 0)
            return f"{self.tool_name}: Found {total} matching anomalies (showing {returned})"

        if self.tool_name == "get_anomaly_detail":
            sev = data.get("severity", "")
            score = data.get("risk_score", "")
            user = data.get("user_id", "")
            return f"Anomaly detail: {sev} severity, risk score {score}, user {user}"

        if self.tool_name == "get_risk_summary":
            totals = data.get("totals", {})
            total = totals.get("total_anomalies", 0)
            critical = totals.get("critical_count", 0)
            users = totals.get("unique_users", 0)
            window = data.get("window_days", "all time")
            return f"Platform summary ({window} days): {total} anomalies, {critical} critical, {users} users"

        if self.tool_name == "get_top_anomalies":
            returned = data.get("returned", 0)
            anomalies = data.get("anomalies", [])
            max_score = anomalies[0].get("risk_score", "N/A") if anomalies else "N/A"
            return f"Retrieved top {returned} anomalies (highest risk score: {max_score})"

        if self.tool_name == "get_investigation":
            findings = data.get("findings") or data.get("investigations") or []
            if isinstance(findings, list):
                return f"Retrieved {len(findings)} investigation finding(s)"
            return "Investigation findings retrieved"

        if self.tool_name == "get_llm_explanations":
            explanations = data.get("explanations", [])
            return f"Generated {len(explanations)} analytical explanation(s)"

        if self.tool_name == "get_root_cause_summary":
            categories = data.get("categories") or data.get("root_causes") or []
            if isinstance(categories, list):
                return f"Root cause distribution: {len(categories)} categories identified"
            return "Root cause summary retrieved"

        if self.tool_name == "get_anomaly_timeline":
            trend = data.get("trend", "")
            period = data.get("window_days", "")
            parts = ["Anomaly timeline retrieved"]
            if period:
                parts[0] += f" ({period} days)"
            if trend:
                parts.append(f"trend: {trend}")
            return " — ".join(parts)

        if self.tool_name == "get_dimension_ranking":
            dim = data.get("dimension", "")
            items = data.get("ranking") or data.get("items") or []
            if isinstance(items, list):
                return f"Top {len(items)} ranked by {dim}" if dim else f"Dimension ranking: {len(items)} entries"
            return "Dimension ranking retrieved"

        if self.tool_name == "get_neo4j_graph":
            edges = data.get("edge_count", 0)
            return f"Knowledge graph: {edges} relationship edges retrieved"

        # --- Generic fallback with count extraction ---
        for key in ("total_matching", "returned", "row_count", "edge_count"):
            if key in data:
                return f"{self.label}: retrieved {data[key]} results"
        return f"{self.label}: data retrieved successfully"

    def _param_hint(self, key: str) -> str:
        """Return a short param hint like ' for <username>' if the param exists."""
        val = self.params.get(key)
        return f" for {val}" if val else ""


class WorkingMemory:
    """
    Scratchpad that the agent writes to during a single query turn.

    Provides:
    - ``thoughts``: ordered list of THOUGHT strings from the agent
    - ``observations``: ordered list of tool results
    - ``entities``: unique users, anomaly IDs, and IPs mentioned
    - ``tools_used``: set of tool names invoked this turn
    - ``token_budget``: remaining token allowance for observations
    """

    def __init__(self, max_observation_tokens: int = 12_000) -> None:
        self._thoughts: list[str] = []
        self._observations: list[Observation] = []
        self._entities: dict[str, set[str]] = {
            "users": set(),
            "anomaly_ids": set(),
            "ips": set(),
        }
        self._tools_used: list[str] = []
        self._max_obs_tokens = max_observation_tokens
        self._obs_tokens_used = 0

    # -- lifecycle ----------------------------------------------------------

    def reset(self) -> None:
        """Clear all state for a new turn."""
        self._thoughts.clear()
        self._observations.clear()
        for s in self._entities.values():
            s.clear()
        self._tools_used.clear()
        self._obs_tokens_used = 0

    # -- thoughts -----------------------------------------------------------

    def add_thought(self, thought: str) -> None:
        self._thoughts.append(thought)

    # -- observations -------------------------------------------------------

    def add_observation(
        self,
        tool_name: str,
        params: dict[str, Any],
        data: Any,
        *,
        tokens: int = 0,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        obs = Observation(
            tool_name=tool_name,
            params=params,
            data=data,
            tokens=tokens,
            success=success,
            error=error,
        )
        self._observations.append(obs)
        self._obs_tokens_used += tokens
        if tool_name not in self._tools_used:
            self._tools_used.append(tool_name)
        # Auto-extract entities from the result
        if success and data:
            self._extract_entities(data)

    def update_last_observation_data(self, compressed_data: Any, new_tokens: int) -> None:
        """Replace the data of the most recent observation (after compression)."""
        if not self._observations:
            return
        old_tokens = self._observations[-1].tokens
        self._observations[-1].data = compressed_data
        self._observations[-1].tokens = new_tokens
        self._obs_tokens_used += new_tokens - old_tokens

    # -- entities -----------------------------------------------------------

    @property
    def entities(self) -> dict[str, set[str]]:
        return self._entities

    # -- queries ------------------------------------------------------------

    @property
    def thoughts(self) -> list[str]:
        return list(self._thoughts)

    @property
    def observations(self) -> list[Observation]:
        return list(self._observations)

    @property
    def tools_used(self) -> list[str]:
        return list(self._tools_used)

    @property
    def tokens_used(self) -> int:
        return self._obs_tokens_used

    @property
    def tokens_remaining(self) -> int:
        return max(0, self._max_obs_tokens - self._obs_tokens_used)

    @property
    def tool_call_count(self) -> int:
        return len(self._observations)

    # -- scratchpad rendering -----------------------------------------------

    @property
    def scratchpad(self) -> str:
        """
        Render the full reasoning trace for injection into the LLM prompt.

        Format matches the ReAct convention::

            THOUGHT: ...
            ACTION: tool_name
            ACTION_INPUT: {"param": "value"}
            OBSERVATION: <tool output or summary>
        """
        parts: list[str] = []
        thought_idx = 0
        obs_idx = 0

        # Interleave thoughts and observations in chronological order.
        # In practice, each thought is followed by an observation,
        # but we handle mismatches gracefully.
        while thought_idx < len(self._thoughts) or obs_idx < len(self._observations):
            if thought_idx < len(self._thoughts):
                parts.append(f"THOUGHT: {self._thoughts[thought_idx]}")
                thought_idx += 1

            if obs_idx < len(self._observations):
                obs = self._observations[obs_idx]
                parts.append(f"ACTION: {obs.tool_name}")
                parts.append(f"ACTION_INPUT: {json.dumps(obs.params, default=str)}")
                if obs.success:
                    obs_text = self._format_observation(obs.data, max_chars=4000)
                    parts.append(f"OBSERVATION: {obs_text}")
                else:
                    parts.append(f"OBSERVATION: ERROR — {obs.error}")
                obs_idx += 1

            parts.append("")  # blank line between steps

        return "\n".join(parts)

    @property
    def scratchpad_compressed(self) -> str:
        """One-line-per-step summary when the full scratchpad is too large."""
        lines: list[str] = []
        for i, obs in enumerate(self._observations, 1):
            lines.append(f"Step {i}: {obs.summary_line()}")
        return "\n".join(lines)

    # -- internal -----------------------------------------------------------

    def _extract_entities(self, data: Any) -> None:
        """Walk tool result dicts to find user_ids, anomaly_ids, IPs."""
        if isinstance(data, dict):
            for key, val in data.items():
                if key in ("user_id", "username") and isinstance(val, str):
                    self._entities["users"].add(val)
                elif key == "anomaly_id" and isinstance(val, str):
                    self._entities["anomaly_ids"].add(val)
                elif key in ("event_ip", "callerIpAddress") and isinstance(val, str):
                    self._entities["ips"].add(val)
                elif isinstance(val, (dict, list)):
                    self._extract_entities(val)
        elif isinstance(data, list):
            for item in data:
                self._extract_entities(item)

    @staticmethod
    def _format_observation(data: Any, max_chars: int = 2000) -> str:
        """Serialise observation data, truncating if needed."""
        try:
            text = json.dumps(data, indent=None, default=str)
        except (TypeError, ValueError):
            text = str(data)
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"... (truncated, {len(text)} chars total)"
