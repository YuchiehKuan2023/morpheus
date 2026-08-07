"""
Agent Core — ReAct loop for agentic conversational AI queries.

Interleaves THOUGHT → ACTION → OBSERVATION steps using the cheap router
model, then synthesises a final ANSWER using the expensive answer model.
Stays within guard-rail budgets and compresses observations as needed.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from modules.ai.conversational.entity_tracker import EntityTracker
from modules.ai.conversational.episodic_memory import EpisodicMemory, extract_entities
from modules.ai.conversational.guard_rails import AgentConfig, GuardRails
from modules.ai.conversational.memory import WorkingMemory
from modules.ai.conversational.planner import QueryPlan, QueryPlanner, needs_planning
from modules.ai.conversational.prompts import (
    FORCE_ANSWER_PROMPT,
    PLAN_INJECTION_TEMPLATE,
    REACT_SYSTEM_PROMPT,
    STEP_PROMPT_TEMPLATE,
    SYNTHESIS_PROMPT,
)
from modules.ai.conversational.reflector import Reflector
from modules.ai.conversational.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TraceStep:
    """A single recorded step in the agent's reasoning trace."""

    kind: str  # "thought" | "action" | "observation" | "plan" | "reflection" | "answer"
    content: str = ""
    tool: str = ""
    params: dict[str, Any] | None = None
    success: bool | None = None
    elapsed_ms: int = 0
    plan_data: dict[str, Any] | None = None  # structured plan info for kind="plan"


@dataclass(slots=True)
class AgentResponse:
    """Final output of a single agent turn."""

    answer: str
    tools_used: list[str]
    steps: int
    sources: list[str]
    reasoning_trace: list[dict[str, Any]] | None = None
    tool_results: dict[str, Any] | None = None  # observation data keyed by tool name


@dataclass(slots=True)
class _ParsedStep:
    """Result of parsing a single LLM reasoning step."""

    type: str  # "action" | "answer"
    thought: str = ""
    action: str = ""
    params: dict[str, Any] | None = None
    answer: str = ""


# ---------------------------------------------------------------------------
# Agent Core
# ---------------------------------------------------------------------------


class AgentCore:
    """
    ReAct agent loop for conversational AI queries.

    Uses the cheap ``router_model`` for reasoning steps and the expensive
    ``answer_model`` for the final synthesis.  All tool execution goes
    through :class:`ToolRegistry`.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        client: Any,  # openai.OpenAI instance
        router_model: str,
        answer_model: str,
        config: AgentConfig | None = None,
    ) -> None:
        self._tools = tool_registry
        self._client = client
        self._router_model = router_model
        self._answer_model = answer_model
        self._config = config or AgentConfig()
        self._guard = GuardRails(self._config)
        self._memory = WorkingMemory(self._config.max_observation_tokens)
        self._planner = QueryPlanner(client, router_model)
        self._reflector = Reflector(client, router_model)
        self._entity_tracker = EntityTracker()
        self._episodic: EpisodicMemory | None = None  # set per-run if session_id provided
        self._max_retries = 3
        self._plan: QueryPlan | None = None
        self._turn_counter = 0
        self._trace: list[TraceStep] = []
        self._last_finish_reason: str | None = None
        self._step_callback: Callable[[dict[str, Any]], None] | None = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(
        self,
        query: str,
        history: list[dict[str, Any]],
        intent: dict[str, Any] | None = None,
        session_id: int | None = None,
        step_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentResponse:
        """
        Execute the ReAct loop until the agent produces an answer
        or the guard-rail budget is exhausted.
        """
        self._guard.reset()
        self._memory.reset()
        self._reflector.reset()
        self._plan = None
        self._trace = []
        self._turn_counter += 1
        self._step_callback = step_callback

        # --- Episodic memory: bind to session + retrieve prior context ---
        episodic_context = ""
        if session_id is not None:
            self._episodic = EpisodicMemory(session_id)
            episodic_context = self._episodic.get_relevant_context(query, max_turns=5)

        # --- Entity resolution: rewrite anaphoric references ---
        resolved_query = self._entity_tracker.resolve_references(query)
        if resolved_query != query:
            logger.info("Entity resolution: %r → %r", query, resolved_query)
            self._memory.add_thought(f'Resolved references: "{query}" → "{resolved_query}"')
            self._emit(TraceStep(kind="thought", content=f'Resolved references: "{query}" → "{resolved_query}"'))

        # --- Planning phase (advisory) ---
        if needs_planning(resolved_query, intent):
            plan = self._planner.generate_plan(resolved_query, intent)
            if plan and plan.steps:
                self._plan = plan
                self._memory.add_thought(f"Plan generated: {plan.goal} ({len(plan.steps)} steps)")
                self._emit(
                    TraceStep(
                        kind="plan",
                        content=plan.summary(),
                        plan_data=self._serialize_plan(),
                    )
                )
                logger.info("Plan: %s", plan.summary())
            else:
                logger.warning("Planning was needed but plan generation returned no steps")
                self._memory.add_thought("Complex query detected — proceeding with adaptive reasoning.")

        # Build the system prompt once per turn (tool schemas are static)
        system = REACT_SYSTEM_PROMPT.format(
            max_iterations=self._config.max_iterations,
            max_tool_calls=self._config.max_tool_calls,
            tool_schemas=self._tools.get_schemas_text(),
        )

        # Inject episodic context into the system prompt if available
        if episodic_context:
            system += (
                "\n\n## Prior conversation context\n"
                "The user has discussed the following topics earlier in this session:\n"
                f"{episodic_context}\n"
                "Use this context to understand follow-up questions and resolve references."
            )

        for step in range(self._config.max_iterations):
            # Guard-rail: iteration budget
            allowed, reason = self._guard.check_iteration(step)
            if not allowed:
                logger.info("Guard rail: %s — forcing answer", reason)
                break

            # Build step prompt
            prompt = STEP_PROMPT_TEMPLATE.format(
                history_count=min(len(history), 6),
                history=self._format_history(history[-6:]),
                scratchpad=self._memory.scratchpad,
                query=resolved_query,
                iterations_left=self._config.max_iterations - step,
                calls_left=self._guard.calls_remaining,
                tokens_left=self._guard.tokens_remaining,
            )

            # Inject plan context if we have an active plan
            if self._plan and self._plan.next_step:
                ns = self._plan.next_step
                prompt += PLAN_INJECTION_TEMPLATE.format(
                    plan_summary=self._plan.summary(),
                    current_step_id=ns.id,
                    current_step_action=ns.action,
                    current_step_purpose=ns.purpose,
                )

            # LLM reasoning step (cheap model)
            logger.info(
                "Step %d: calling router model (%d obs, %d tokens used)",
                step,
                len(self._memory.observations),
                self._memory.tokens_used,
            )
            raw = self._llm_call(
                system_prompt=system,
                user_prompt=prompt,
                model=self._router_model,
                max_tokens=800,
                temperature=0.2,
            )
            if raw is None:
                logger.error("LLM returned None on step %d — forcing answer", step)
                break

            step_truncated = self._last_finish_reason == "length"
            parsed = self._parse_step(raw)
            logger.info(
                "Step %d: parsed as %s%s%s",
                step,
                parsed.type,
                f" → {parsed.action}" if parsed.action else "",
                " (TRUNCATED)" if step_truncated else "",
            )

            # --- ANSWER branch ---
            if parsed.type == "answer":
                if parsed.thought:
                    self._memory.add_thought(parsed.thought)
                    self._emit(TraceStep(kind="thought", content=parsed.thought))

                # Skip reflection when the router answer was truncated —
                # a partial answer will always fail quality review, wasting
                # an iteration.  Go straight to the answer model.
                if not step_truncated and self._memory.observations and self._reflector.reflections_remaining > 0:
                    reflection = self._reflector.reflect(
                        query,
                        parsed.answer,
                        self._memory.scratchpad_compressed,
                    )
                    self._emit(TraceStep(kind="reflection", content=reflection.feedback, success=reflection.sufficient))
                    if not reflection.sufficient and step < self._config.max_iterations - 1:
                        self._memory.add_thought(f"Self-check: {reflection.feedback}. Gathering more data.")
                        continue

                # Generate full answer with the answer model (the router's
                # inline answer is too short).  Fall back to the router
                # answer if the full-generation call fails.
                #
                # Mark any "synthesize" plan step as completed since we are
                # now producing the final synthesis.
                if self._plan:
                    # Mark synthesize step completed and skip any remaining
                    # pending steps the agent chose not to execute.
                    for ps in self._plan.steps:
                        if ps.action == "synthesize" and not ps.completed:
                            self._plan.mark_completed(ps.id)
                        elif not ps.completed and not ps.skipped:
                            self._plan.mark_skipped(ps.id)

                logger.info(
                    "Generating full answer with %s (scratchpad: %d chars, %d observations)",
                    self._answer_model,
                    len(self._memory.scratchpad),
                    len(self._memory.observations),
                )
                full_answer = self._generate_full_answer(resolved_query or query)
                if full_answer:
                    logger.info(
                        "Full answer generated: %d chars (finish_reason=%s)", len(full_answer), self._last_finish_reason
                    )
                else:
                    logger.warning(
                        "Full answer generation failed — falling back to router's inline answer (%d chars)",
                        len(parsed.answer),
                    )
                    full_answer = parsed.answer

                self._emit(TraceStep(kind="answer"))
                return self._build_response(full_answer, step + 1, query, resolved_query)

            # --- ACTION branch ---
            if parsed.thought:
                self._memory.add_thought(parsed.thought)
                self._emit(TraceStep(kind="thought", content=parsed.thought))

            tool_name = parsed.action
            params = parsed.params or {}

            # Guard-rail: action check
            allowed, reason = self._guard.allow_action(tool_name, params)
            if not allowed:
                logger.info("Guard rail blocked %s: %s", tool_name, reason)
                self._memory.add_thought(f"Blocked: {reason}. Choosing a different approach.")
                self._emit(TraceStep(kind="thought", content=f"Blocked: {reason}"))
                continue

            # Execute via registry
            t0 = time.time()
            result = self._tools.execute(tool_name, params)
            elapsed_ms = int((time.time() - t0) * 1000)
            self._guard.record_call(tool_name, params, result.tokens_estimate)
            logger.info(
                "Step %d: %s(%s) → %s in %dms (%d tokens)",
                step,
                tool_name,
                json.dumps(params, default=str),
                "OK" if result.success else f"FAIL: {result.error}",
                elapsed_ms,
                result.tokens_estimate,
            )

            self._emit(
                TraceStep(
                    kind="action",
                    tool=tool_name,
                    params=params,
                    elapsed_ms=elapsed_ms,
                )
            )

            self._memory.add_observation(
                tool_name,
                params,
                result.data if result.success else None,
                tokens=result.tokens_estimate,
                success=result.success,
                error=result.error,
            )

            obs_summary = result.error or "" if not result.success else self._memory.observations[-1].summary_line()
            self._emit(
                TraceStep(
                    kind="observation",
                    content=obs_summary,
                    tool=tool_name,
                    success=result.success,
                    elapsed_ms=elapsed_ms,
                )
            )

            if not result.success:
                self._memory.add_thought(
                    f"{tool_name} failed: {result.error}. I should try a different tool or different parameters."
                )
                # Skip dependent plan steps if this one failed
                if self._plan:
                    for ps in self._plan.steps:
                        if ps.action == tool_name and not ps.completed:
                            self._plan.skip_dependents(ps.id)
                            ps.skipped = True
                            break
            else:
                # Mark the matching plan step as completed
                if self._plan:
                    for ps in self._plan.steps:
                        if ps.action == tool_name and not ps.completed and not ps.skipped:
                            self._plan.mark_completed(ps.id)
                            break

            # Compress if the single observation is too large
            if result.success and result.tokens_estimate > self._config.max_single_observation_tokens:
                compressed = self._compress_observation(query, result.data)
                new_tokens = len(json.dumps(compressed, default=str)) // 4
                self._memory.update_last_observation_data(compressed, new_tokens)

        # Budget exhausted — force an answer from what we have
        return self._force_answer(query, history, resolved_query)

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------

    def _llm_call(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 600,
        temperature: float = 0.2,
    ) -> str | None:
        """Single LLM chat completion with retry."""
        self._last_finish_reason = None
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        for attempt in range(self._max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                choice = response.choices[0]
                self._last_finish_reason = getattr(choice, "finish_reason", None)
                if self._last_finish_reason == "length":
                    logger.warning(
                        "LLM response truncated (finish_reason=length, model=%s, max_tokens=%d)",
                        model,
                        max_tokens,
                    )
                elif self._last_finish_reason and self._last_finish_reason not in ("stop",):
                    logger.warning(
                        "LLM response ended with finish_reason=%s (model=%s)",
                        self._last_finish_reason,
                        model,
                    )
                return (choice.message.content or "").strip()
            except Exception as exc:
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)
                    logger.warning("LLM call attempt %d failed: %s", attempt + 1, exc)
                else:
                    logger.error("LLM call failed after %d retries: %s", self._max_retries, exc)
        return None

    # ------------------------------------------------------------------
    # Step parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_step(raw: str) -> _ParsedStep:
        """
        Parse the LLM's output into a structured step.

        Expected formats::

            THOUGHT: ...
            ACTION: tool_name
            ACTION_INPUT: {"param": "value"}

        or::

            THOUGHT: ...
            ANSWER: final answer text

        or just::

            ANSWER: final answer text
        """
        thought = ""
        action = ""
        action_input: dict[str, Any] = {}
        # answer = ""

        # Extract THOUGHT (everything between THOUGHT: and ACTION:/ANSWER:)
        thought_match = re.search(
            r"THOUGHT:\s*(.+?)(?=\nACTION:|ANSWER:|\Z)",
            raw,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            thought = thought_match.group(1).strip()

        # Check for ANSWER first (takes priority)
        answer_match = re.search(r"ANSWER:\s*(.+)", raw, re.DOTALL | re.IGNORECASE)
        if answer_match:
            return _ParsedStep(type="answer", thought=thought, answer=answer_match.group(1).strip())

        # Extract ACTION and ACTION_INPUT
        action_match = re.search(r"ACTION:\s*(\S+)", raw, re.IGNORECASE)
        if action_match:
            action = action_match.group(1).strip()

        input_match = re.search(r"ACTION_INPUT:\s*(\{.*?\})", raw, re.DOTALL | re.IGNORECASE)
        if input_match:
            try:
                action_input = json.loads(input_match.group(1))
            except json.JSONDecodeError:
                logger.warning("Failed to parse ACTION_INPUT: %s", input_match.group(1))

        if action:
            return _ParsedStep(type="action", thought=thought, action=action, params=action_input)

        # Fallback: if there's no ACTION or ANSWER marker, treat as answer
        # (the LLM sometimes just writes a response without the prefix)
        return _ParsedStep(type="answer", thought=thought, answer=raw.strip())

    # ------------------------------------------------------------------
    # Full answer generation & force answer
    # ------------------------------------------------------------------

    def _generate_full_answer(self, query: str, *, budget_exhausted: bool = False) -> str | None:
        """Generate a complete answer using the answer model with full token budget."""
        template = FORCE_ANSWER_PROMPT if budget_exhausted else SYNTHESIS_PROMPT
        prompt = template.format(
            query=query,
            scratchpad=self._memory.scratchpad,
        )
        return self._llm_call(
            system_prompt=(
                "You are a senior security analyst AI for a Digital Fingerprinting Platform. "
                "Provide a thorough, grounded answer based only on the data collected."
            ),
            user_prompt=prompt,
            model=self._answer_model,
            max_tokens=3800,
            temperature=0.0,
        )

    def _force_answer(
        self, query: str, history: list[dict[str, Any]], resolved_query: str | None = None
    ) -> AgentResponse:
        """Generate a best-effort answer when the reasoning budget is exhausted."""
        logger.info(
            "Budget exhausted — forcing answer with %s (%d observations)",
            self._answer_model,
            len(self._memory.observations),
        )
        answer = self._generate_full_answer(resolved_query or query, budget_exhausted=True)
        return self._build_response(
            answer or "I was unable to generate a complete answer. Please try rephrasing your question.",
            self._config.max_iterations,
            query,
            resolved_query,
        )

    def _compress_observation(self, query: str, data: Any) -> dict[str, Any]:
        """
        Compress a large tool result to fit within the single-observation budget.

        Strategy: keep essential fields (IDs, scores, severities), drop verbose text.
        """
        if isinstance(data, dict):
            compressed: dict[str, Any] = {}
            essential_keys = {
                "anomaly_id",
                "user_id",
                "username",
                "timestamp",
                "severity",
                "risk_score",
                "anomaly_score",
                "root_cause",
                "status",
                "total_matching",
                "returned",
                "row_count",
                "edge_count",
                "trend",
                "window_days",
                "scope",
            }
            for key, value in data.items():
                if key in essential_keys:
                    compressed[key] = value
                elif isinstance(value, list):
                    # Keep first 5 items, strip verbose fields
                    compressed[key] = [
                        self._strip_record(item) if isinstance(item, dict) else item for item in value[:5]
                    ]
                    if len(value) > 5:
                        compressed[f"_{key}_total"] = len(value)
                elif isinstance(value, dict) and len(json.dumps(value, default=str)) > 500:
                    compressed[key] = dict(list(value.items())[:8])
                else:
                    compressed[key] = value
            return compressed
        return data

    @staticmethod
    def _strip_record(record: dict[str, Any]) -> dict[str, Any]:
        """Strip verbose text fields from a single record, keeping identifiers and scores."""
        keep = {
            "anomaly_id",
            "user_id",
            "username",
            "timestamp",
            "severity",
            "risk_score",
            "anomaly_score",
            "root_cause",
            "status",
            "anomaly_count",
            "max_risk_score",
            "avg_risk_score",
            "dimension_value",
            "similarity_score",
            "period",
            "critical_count",
            "high_count",
            "medium_count",
            "low_count",
        }
        return {k: v for k, v in record.items() if k in keep}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_response(
        self, answer: str, steps: int, original_query: str = "", resolved_query: str | None = None
    ) -> AgentResponse:
        """Construct the final AgentResponse and record the turn in episodic memory."""
        from frontend.backend.services.conversational_ai_service import _TOOL_SOURCE_LABELS

        tools = self._memory.tools_used
        sources = list(dict.fromkeys(_TOOL_SOURCE_LABELS.get(t, "PostgreSQL") for t in tools))

        # Update entity tracker with entities discovered this turn
        self._entity_tracker.update_from_memory(self._memory.entities, self._turn_counter)

        # Also extract entities from the query and answer text
        for e in extract_entities(original_query or ""):
            self._entity_tracker.update({e}, "user" if "@" in e else "anomaly_id", self._turn_counter)

        # Record turn in episodic memory (fire-and-forget)
        if self._episodic is not None:
            all_entities = set()
            for entity_set in self._memory.entities.values():
                all_entities.update(entity_set)
            all_entities.update(extract_entities(original_query or ""))
            try:
                self._episodic.record_turn(
                    query=original_query or (resolved_query or ""),
                    answer=answer,
                    tools_used=tools,
                    entities=all_entities,
                )
            except Exception as exc:
                logger.warning("Failed to record episodic memory: %s", exc)

        # Collect raw observation data keyed by tool name for contextual followups
        obs_data: dict[str, Any] = {}
        for obs in self._memory.observations:
            if obs.success and obs.data is not None:
                obs_data[obs.tool_name] = obs.data

        return AgentResponse(
            answer=answer,
            tools_used=tools,
            steps=steps,
            sources=sources,
            reasoning_trace=self._serialize_trace(),
            tool_results=obs_data,
        )

    def _emit(self, ts: TraceStep) -> None:
        """Record a trace step and push it to the streaming callback if set."""
        self._trace.append(ts)
        if self._step_callback is not None:
            d = self._serialize_step(ts)
            try:
                self._step_callback(d)
            except Exception as exc:
                logger.warning("Step callback error: %s", exc)

    @staticmethod
    def _serialize_step(ts: TraceStep) -> dict[str, Any]:
        """Convert a single TraceStep to a JSON-safe dict."""
        d: dict[str, Any] = {"kind": ts.kind}
        if ts.content:
            d["content"] = ts.content
        if ts.tool:
            d["tool"] = ts.tool
        if ts.params:
            d["params"] = ts.params
        if ts.success is not None:
            d["success"] = ts.success
        if ts.elapsed_ms:
            d["elapsed_ms"] = ts.elapsed_ms
        if ts.plan_data:
            d["plan"] = ts.plan_data["plan"]
            d["steps"] = ts.plan_data["steps"]
        return d

    def _serialize_trace(self) -> list[dict[str, Any]]:
        """Convert TraceStep list to JSON-safe dicts for the API response."""
        # Finalize plan step statuses before serializing
        self._finalize_plan_trace()
        return [self._serialize_step(ts) for ts in self._trace]

    def _serialize_plan(self) -> dict[str, Any]:
        """Serialize the current plan into a structured dict."""
        if not self._plan:
            return {}
        return {
            "plan": self._plan.goal,
            "steps": [
                {
                    "id": s.id,
                    "action": s.action,
                    "purpose": s.purpose,
                    "status": ("completed" if s.completed else "skipped" if s.skipped else "pending"),
                }
                for s in self._plan.steps
            ],
        }

    def _finalize_plan_trace(self) -> None:
        """Update the plan trace entry with final step statuses."""
        if not self._plan:
            return
        for ts in self._trace:
            if ts.kind == "plan":
                ts.plan_data = self._serialize_plan()
                ts.content = self._plan.summary()
                break

    @staticmethod
    def _format_history(history: list[dict[str, Any]], max_chars: int = 500) -> str:
        """Format conversation history for injection into the step prompt."""
        if not history:
            return "(no prior messages)"
        parts: list[str] = []
        for msg in history:
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))
            if len(content) > max_chars:
                content = content[:max_chars] + "…"
            parts.append(f"{role}: {content}")
        return "\n".join(parts)
