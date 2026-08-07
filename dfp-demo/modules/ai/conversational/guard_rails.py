"""
Guard Rails — safety constraints for the ReAct agent loop.

Enforces:
- Maximum iteration count (prevent infinite loops)
- Maximum tool call count (prevent runaway tool use)
- Token budget (prevent context window overflow)
- Blocked tools list (prevent dangerous operations in agentic mode)
- Duplicate call detection (same tool + same params)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Configurable limits for the agentic loop."""

    max_iterations: int = 8
    max_tool_calls: int = 15
    max_observation_tokens: int = 12_000
    max_single_observation_tokens: int = 3_000
    blocked_tools: tuple[str, ...] = ("query_database",)


class GuardRails:
    """
    Runtime safety checks applied before each agent action.

    Tracks cumulative state (calls made, tokens consumed) and returns
    a ``(allowed, reason)`` tuple for each proposed action.
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self._config = config or AgentConfig()
        self._call_count = 0
        self._tokens_consumed = 0
        self._call_history: list[str] = []  # "tool_name:params_hash" dedup keys

    # -- public API ---------------------------------------------------------

    def allow_action(self, tool_name: str, params: dict) -> tuple[bool, str]:
        """
        Check whether the agent may execute *tool_name* with *params*.

        Returns ``(True, "")`` if allowed, or ``(False, reason)`` if blocked.
        """
        # 1. Blocked tool
        if tool_name in self._config.blocked_tools:
            return False, f"Tool '{tool_name}' is blocked in agentic mode"

        # 2. Tool-call budget
        if self._call_count >= self._config.max_tool_calls:
            return False, f"Tool-call budget exhausted ({self._config.max_tool_calls})"

        # 3. Token budget
        if self._tokens_consumed >= self._config.max_observation_tokens:
            return False, f"Observation token budget exhausted ({self._config.max_observation_tokens})"

        # 4. Exact-duplicate call (same tool + identical params)
        dedup_key = f"{tool_name}:{json.dumps(params, sort_keys=True, default=str)}"
        if dedup_key in self._call_history:
            return False, f"Duplicate call: {tool_name} already called with same parameters"

        return True, ""

    def record_call(self, tool_name: str, params: dict, tokens: int) -> None:
        """Record that a call was executed (must be called after allow_action)."""
        dedup_key = f"{tool_name}:{json.dumps(params, sort_keys=True, default=str)}"
        self._call_history.append(dedup_key)
        self._call_count += 1
        self._tokens_consumed += tokens

    def check_iteration(self, step: int) -> tuple[bool, str]:
        """Check whether iteration *step* (0-based) is within budget."""
        if step >= self._config.max_iterations:
            return False, f"Iteration budget exhausted ({self._config.max_iterations})"
        return True, ""

    # -- state queries ------------------------------------------------------

    @property
    def calls_remaining(self) -> int:
        return max(0, self._config.max_tool_calls - self._call_count)

    @property
    def tokens_remaining(self) -> int:
        return max(0, self._config.max_observation_tokens - self._tokens_consumed)

    @property
    def config(self) -> AgentConfig:
        return self._config

    # -- reset --------------------------------------------------------------

    def reset(self) -> None:
        """Reset all counters for a new query turn."""
        self._call_count = 0
        self._tokens_consumed = 0
        self._call_history.clear()
