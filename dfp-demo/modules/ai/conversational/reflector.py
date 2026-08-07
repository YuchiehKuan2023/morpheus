"""
Reflector — self-evaluates proposed answers for quality and completeness.

Extracted from the inline ``_reflect`` helper in :class:`AgentCore` so it
can be reused and configured independently.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from .prompts import REFLECT_PROMPT

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReflectionResult:
    """Outcome of a reflection check."""

    sufficient: bool
    feedback: str
    confidence: float = 1.0  # 0..1, derived from wording


class Reflector:
    """
    Evaluates whether a proposed answer fully addresses the original query.

    Uses the cheap router model for a lightweight quality review with a
    4-point quality checklist (factual grounding, completeness, specificity,
    query coverage).
    """

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        max_reflections: int = 2,
    ) -> None:
        self._client = client
        self._model = model
        self._max_reflections = max_reflections
        self._reflection_count = 0

    def reset(self) -> None:
        self._reflection_count = 0

    @property
    def reflections_remaining(self) -> int:
        return max(0, self._max_reflections - self._reflection_count)

    def reflect(
        self,
        query: str,
        proposed_answer: str,
        scratchpad_compressed: str,
    ) -> ReflectionResult:
        """
        Evaluate whether *proposed_answer* satisfactorily answers *query*.

        Returns a :class:`ReflectionResult` with ``sufficient`` flag and
        free-text ``feedback`` explaining any gaps.
        """
        if self._reflection_count >= self._max_reflections:
            return ReflectionResult(
                sufficient=True,
                feedback="Reflection budget exhausted — accepting answer",
                confidence=0.5,
            )

        self._reflection_count += 1

        prompt = REFLECT_PROMPT.format(
            query=query,
            scratchpad_compressed=scratchpad_compressed,
            proposed_answer=proposed_answer,
        )

        raw = self._llm_call(prompt)
        if raw is None:
            return ReflectionResult(
                sufficient=True,
                feedback="Reflection call failed — accepting answer",
                confidence=0.3,
            )

        return self._parse(raw)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _llm_call(self, user_prompt: str) -> str | None:
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "You are a quality reviewer."},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=150,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            logger.warning("Reflection LLM call failed: %s", exc)
            return None

    @staticmethod
    def _parse(raw: str) -> ReflectionResult:
        """Parse the SUFFICIENT / FEEDBACK response format."""
        # Extract sufficient flag
        after_sufficient = raw.lower().split("sufficient:")[-1][:20].lower()
        sufficient = "yes" in after_sufficient

        # Extract feedback
        feedback_match = re.search(r"FEEDBACK:\s*(.+)", raw, re.DOTALL | re.IGNORECASE)
        feedback = feedback_match.group(1).strip() if feedback_match else raw.strip()

        # Derive crude confidence from wording
        confidence = 0.9 if sufficient else 0.4
        low_confidence_markers = ["partial", "missing", "incomplete", "lacks", "insufficient"]
        if any(m in raw.lower() for m in low_confidence_markers):
            confidence = min(confidence, 0.5)

        return ReflectionResult(
            sufficient=sufficient,
            feedback=feedback,
            confidence=confidence,
        )
