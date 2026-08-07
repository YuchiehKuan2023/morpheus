"""
Base agent interface for the Multi-Agent System.

Every concrete agent (ForensicsAgent, InvestigationAgent, RemediationAgent)
must subclass BaseAgent and implement the `_execute` method.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentTask:
    """Input contract passed to every agent."""

    investigation_id: str
    anomaly_id: str
    anomaly_data: dict[str, Any]  # full enriched_anomalies row as dict
    context: dict[str, Any] = field(default_factory=dict)
    # context carries outputs from earlier agents, e.g.:
    #   context["forensics_result"]     → ForensicsAgent output dict
    #   context["investigation_result"] → InvestigationAgent output dict


@dataclass
class AgentResult:
    """Output contract returned by every agent."""

    agent_type: str  # 'forensics' | 'investigation' | 'remediation'
    status: str  # 'complete' | 'failed' | 'skipped'
    result: dict[str, Any]  # agent-specific payload (stored in agent_findings.result)
    confidence: float = 0.0  # 0.0 – 1.0
    latency_ms: int = 0
    llm_tokens_used: int = 0
    error: str | None = None


class BaseAgent(ABC):
    """Abstract base for all agents. Handles timing and error wrapping."""

    TIMEOUT_SECONDS: int = 30  # override in subclass if needed

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Return agent identifier string: 'forensics' | 'investigation' | 'remediation'."""

    @abstractmethod
    def _execute(self, task: AgentTask) -> AgentResult:
        """Core agent logic — implement in each subclass."""

    def run(self, task: AgentTask) -> AgentResult:
        """Public entry point. Wraps _execute with timing and error handling."""
        start = time.monotonic()
        try:
            logger.info(
                "[%s] Starting  investigation_id=%s  anomaly_id=%s",
                self.agent_type,
                task.investigation_id,
                task.anomaly_id,
            )
            result = self._execute(task)
            result.latency_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "[%s] Complete — confidence=%.2f  latency=%dms",
                self.agent_type,
                result.confidence,
                result.latency_ms,
            )
            return result
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.exception(
                "[%s] Failed after %dms: %s",
                self.agent_type,
                latency_ms,
                exc,
            )
            return AgentResult(
                agent_type=self.agent_type,
                status="failed",
                result={},
                latency_ms=latency_ms,
                error=str(exc),
            )
