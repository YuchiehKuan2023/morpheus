"""
Tool Registry — formal catalogue of agent-callable tools with metadata.

Wraps the existing 14 ``_fetch_*`` handlers from
:class:`DFPConversationalAIService` and exposes them through a
:class:`ToolRegistry` that the :class:`AgentCore` uses for schema
generation, parameter validation, execution with retry/fallback,
and token-budget tracking.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Immutable specification for a single tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Callable[..., Any]  # _fetch_* method reference
    estimated_tokens: int = 500  # Typical output size in tokens
    max_retries: int = 1  # Retry count on transient failure
    fallback: str | None = None  # Alt tool name if this one fails
    read_only: bool = True  # All current tools are read-only
    cacheable: bool = False  # Cache results within the session?
    cache_ttl: int = 0  # Seconds to cache (0 = no cache)
    source_label: str = "PostgreSQL"  # Badge shown in UI
    display_name: str = ""  # Human-readable name


@dataclass(slots=True)
class ToolResult:
    """Outcome of a single tool execution."""

    success: bool
    data: Any = None
    error: str | None = None
    tokens_estimate: int = 0
    elapsed_ms: int = 0
    was_fallback: bool = False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Central registry for all agent-callable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._cache: dict[str, tuple[float, Any]] = {}  # key → (expires_at, data)

    # -- registration -------------------------------------------------------

    def register(self, spec: ToolSpec) -> None:
        """Register a tool specification."""
        self._tools[spec.name] = spec

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools)

    # -- schema generation --------------------------------------------------

    def get_schemas_text(self) -> str:
        """Return a compact text listing of all tools for the ReAct prompt."""
        parts: list[str] = []
        for spec in self._tools.values():
            params = spec.parameters.get("properties", {})
            required = spec.parameters.get("required", [])
            param_lines: list[str] = []
            for pname, pschema in params.items():
                req = " (required)" if pname in required else ""
                ptype = pschema.get("type", "string")
                desc = pschema.get("description", "")
                enum = pschema.get("enum")
                if enum:
                    desc += f" Values: {', '.join(str(v) for v in enum)}"
                param_lines.append(f"    {pname}: {ptype}{req} — {desc}")
            params_block = "\n".join(param_lines) if param_lines else "    (no parameters)"
            parts.append(f"• {spec.name}\n  {spec.description}\n  Parameters:\n{params_block}")
        return "\n\n".join(parts)

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions in OpenAI function-calling format."""
        schemas: list[dict[str, Any]] = []
        for spec in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    },
                }
            )
        return schemas

    # -- execution ----------------------------------------------------------

    def execute(self, name: str, params: dict[str, Any]) -> ToolResult:
        """
        Execute a tool by name with the given parameters.

        Handles validation, retry with back-off, session caching,
        and automatic fallback to an alternative tool.
        """
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(success=False, error=f"Unknown tool: {name}")

        # Check session cache
        cache_key = f"{name}:{json.dumps(params, sort_keys=True)}"
        if spec.cacheable and cache_key in self._cache:
            expires_at, cached_data = self._cache[cache_key]
            if time.monotonic() < expires_at:
                logger.debug("Cache hit for %s", name)
                return ToolResult(
                    success=True,
                    data=cached_data,
                    tokens_estimate=self._estimate_tokens(cached_data),
                )

        # Validate parameters
        errors = self._validate_params(spec.parameters, params)
        if errors:
            return ToolResult(success=False, error=f"Invalid parameters: {'; '.join(errors)}")

        # Execute with retry
        last_error = ""
        for attempt in range(spec.max_retries + 1):
            t0 = time.monotonic()
            try:
                data = spec.handler(**params)
                elapsed = int((time.monotonic() - t0) * 1000)
                tokens = self._estimate_tokens(data)

                # Populate cache
                if spec.cacheable and spec.cache_ttl > 0:
                    self._cache[cache_key] = (time.monotonic() + spec.cache_ttl, data)

                return ToolResult(success=True, data=data, tokens_estimate=tokens, elapsed_ms=elapsed)
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Tool %s attempt %d/%d failed: %s",
                    name,
                    attempt + 1,
                    spec.max_retries + 1,
                    last_error,
                )
                if attempt < spec.max_retries:
                    time.sleep(0.5 * (attempt + 1))  # simple back-off

        # All retries exhausted — try fallback
        if spec.fallback and spec.fallback in self._tools:
            logger.info("Falling back from %s to %s", name, spec.fallback)
            result = self.execute(spec.fallback, params)
            result.was_fallback = True
            return result

        return ToolResult(success=False, error=last_error)

    def clear_cache(self) -> None:
        """Clear the session-scoped result cache."""
        self._cache.clear()

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _validate_params(schema: dict[str, Any], params: dict[str, Any]) -> list[str]:
        """Light-weight JSON Schema validation (required fields + enum checks)."""
        errors: list[str] = []
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        for req_field in required:
            if req_field not in params:
                errors.append(f"missing required parameter '{req_field}'")

        for pname, pvalue in params.items():
            if pname not in properties:
                continue  # tolerate extra params — LLMs sometimes add them
            pschema = properties[pname]
            enum = pschema.get("enum")
            if enum and pvalue not in enum:
                errors.append(f"'{pname}' must be one of {enum}, got '{pvalue}'")

        return errors

    @staticmethod
    def _estimate_tokens(data: Any) -> int:
        """Rough token count based on JSON serialisation length."""
        try:
            text = json.dumps(data, default=str)
        except (TypeError, ValueError):
            text = str(data)
        # ~4 chars per token is a standard approximation
        return len(text) // 4


# ---------------------------------------------------------------------------
# Factory — builds a ToolRegistry from an existing service instance
# ---------------------------------------------------------------------------


def build_registry(service: Any) -> ToolRegistry:
    """
    Build a :class:`ToolRegistry` from a :class:`DFPConversationalAIService`.

    The service's ``_fetch_*`` methods become the tool handlers.
    All metadata (token estimates, retry policy, cacheability, etc.)
    is assigned per tool based on its data source and typical output size.
    """
    registry = ToolRegistry()

    # Helper to build a spec concisely.  `desc` and `params` are extracted
    # from the existing DFP_CHAT_TOOLS list so the schemas stay in sync.
    _tool_defs: dict[str, dict[str, Any]] = {}
    from frontend.backend.services.conversational_ai_service import DFP_CHAT_TOOLS

    for td in DFP_CHAT_TOOLS:
        fn = td["function"]
        _tool_defs[fn["name"]] = {
            "description": fn["description"],
            "parameters": fn["parameters"],
        }

    def _reg(
        name: str,
        handler: Callable[..., Any],
        *,
        estimated_tokens: int = 500,
        max_retries: int = 1,
        fallback: str | None = None,
        cacheable: bool = False,
        cache_ttl: int = 0,
        source_label: str = "PostgreSQL",
        display_name: str = "",
    ) -> None:
        td = _tool_defs.get(name)
        if td is None:
            logger.warning("Tool %s not found in DFP_CHAT_TOOLS — skipping", name)
            return
        registry.register(
            ToolSpec(
                name=name,
                description=td["description"],
                parameters=td["parameters"],
                handler=handler,
                estimated_tokens=estimated_tokens,
                max_retries=max_retries,
                fallback=fallback,
                cacheable=cacheable,
                cache_ttl=cache_ttl,
                source_label=source_label,
                display_name=display_name or name,
            )
        )

    # ---- PostgreSQL tools (fast, low-token) ----
    _reg(
        "search_anomalies",
        service._fetch_search_anomalies,
        estimated_tokens=600,
        cacheable=True,
        cache_ttl=30,
        display_name="Filtered Anomaly Search",
    )

    _reg(
        "get_anomaly_detail",
        service._fetch_get_anomaly_detail,
        estimated_tokens=800,
        cacheable=True,
        cache_ttl=60,
        display_name="Anomaly Detail Record",
    )

    _reg(
        "get_user_profile",
        service._fetch_get_user_profile,
        estimated_tokens=600,
        cacheable=True,
        cache_ttl=60,
        display_name="User Profile",
    )

    _reg(
        "get_risk_summary",
        service._fetch_get_risk_summary,
        estimated_tokens=1200,
        cacheable=True,
        cache_ttl=30,
        display_name="Platform Risk Summary",
    )

    _reg(
        "get_top_anomalies",
        service._fetch_get_top_anomalies,
        estimated_tokens=800,
        cacheable=True,
        cache_ttl=30,
        display_name="Top Anomalies by Risk Score",
    )

    _reg(
        "get_investigation",
        service._fetch_get_investigation,
        estimated_tokens=1000,
        max_retries=2,
        display_name="AI Agent Investigation Findings",
    )

    _reg(
        "get_llm_explanations",
        service._fetch_get_llm_explanations,
        estimated_tokens=900,
        display_name="LLM Analytical Explanations",
    )

    _reg(
        "get_root_cause_summary",
        service._fetch_get_root_cause_summary,
        estimated_tokens=400,
        cacheable=True,
        cache_ttl=60,
        source_label="Analytics",
        display_name="Root Cause Distribution",
    )

    _reg(
        "get_anomaly_timeline",
        service._fetch_get_anomaly_timeline,
        estimated_tokens=700,
        cacheable=True,
        cache_ttl=30,
        source_label="Analytics",
        display_name="Anomaly Timeline & Trend",
    )

    _reg(
        "get_dimension_ranking",
        service._fetch_get_dimension_ranking,
        estimated_tokens=600,
        cacheable=True,
        cache_ttl=30,
        source_label="Analytics",
        display_name="Anomaly Dimension Ranking",
    )

    _reg(
        "get_user_behaviour_baseline",
        service._fetch_get_user_behaviour_baseline,
        estimated_tokens=500,
        cacheable=True,
        cache_ttl=120,
        display_name="User Behaviour Baseline",
    )

    # ---- Qdrant / vector tools ----
    _reg(
        "semantic_search_anomalies",
        service._fetch_semantic_search_anomalies,
        estimated_tokens=800,
        max_retries=2,
        fallback="search_anomalies",
        source_label="Qdrant",
        display_name="Semantic Vector Search (Qdrant)",
    )

    # ---- Neo4j ----
    _reg(
        "get_neo4j_graph",
        service._fetch_get_neo4j_graph,
        estimated_tokens=600,
        max_retries=2,
        source_label="Knowledge Graph",
        display_name="Knowledge Graph Relationships",
    )

    # ---- Raw SQL (blocked in agentic mode by guard rails) ----
    _reg("query_database", service._fetch_query_database, estimated_tokens=800, display_name="Ad-hoc Database Query")

    # ---- Hybrid RAG search (Week 27) ----
    _register_hybrid_search(registry)

    return registry


# ---------------------------------------------------------------------------
# Hybrid search tool — uses HybridRetriever + ContextCompressor
# ---------------------------------------------------------------------------


def _register_hybrid_search(registry: ToolRegistry) -> None:
    """Register the ``hybrid_search`` tool that combines dense + sparse + graph + structured."""

    _retriever = None
    _compressor = None

    def _get_retriever():
        nonlocal _retriever
        if _retriever is None:
            from modules.ai.conversational.advanced_rag import HybridRetriever

            _retriever = HybridRetriever()
        return _retriever

    def _get_compressor():
        nonlocal _compressor
        if _compressor is None:
            from modules.ai.conversational.context_compressor import ContextCompressor

            _compressor = ContextCompressor()
        return _compressor

    def _hybrid_search_handler(
        query: str = "",
        severity: str | None = None,
        user_id: str | None = None,
        days: int | None = None,
        limit: int = 10,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Multi-strategy hybrid search with RRF merging."""
        from modules.ai.conversational.advanced_rag import analyze_query

        # Build context from parameters
        ctx = analyze_query(query)
        ctx.max_results = min(int(limit), 20)

        # Inject explicit filters if provided
        if severity:
            ctx.filters["severity"] = severity.upper()
            ctx.use_structured = True
        if user_id:
            ctx.filters["user_id"] = user_id
            ctx.use_structured = True
            ctx.entities.append(user_id)
            ctx.use_graph = True
        if days:
            ctx.filters["days"] = int(days)
            ctx.use_structured = True

        retriever = _get_retriever()
        results = retriever.retrieve(query, ctx)

        compressor = _get_compressor()
        return compressor.compress_to_dict(results, token_budget=3000)

    registry.register(
        ToolSpec(
            name="hybrid_search",
            description=(
                "Advanced multi-strategy search combining semantic vectors (Qdrant), "
                "full-text search (PostgreSQL FTS), knowledge graph (Neo4j), and "
                "structured SQL filters. Results are merged via Reciprocal Rank Fusion (RRF). "
                "Use this for complex or broad queries. For simple ID lookups use get_anomaly_detail."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query describing what to find",
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
                        "description": "Optional severity filter",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Optional user email filter",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Optional time range filter (last N days)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default 10, max 20)",
                    },
                },
                "required": ["query"],
            },
            handler=_hybrid_search_handler,
            estimated_tokens=1000,
            max_retries=1,
            fallback="semantic_search_anomalies",
            source_label="Hybrid RAG",
            display_name="Hybrid Multi-Strategy Search",
        )
    )


# ---------------------------------------------------------------------------
# Meta-tools — operate on the agent's own state, not external data
# ---------------------------------------------------------------------------


def register_meta_tools(registry: ToolRegistry, agent: Any) -> None:
    """
    Register meta-tools that operate on the agent's working state.

    These are registered *after* ``build_registry()`` because they need
    a reference to the running :class:`AgentCore`.
    """

    def _summarize_results(**_kwargs: Any) -> dict[str, Any]:
        """Compress the current scratchpad into a concise summary."""
        obs = agent._memory.observations
        if not obs:
            return {"summary": "No observations collected yet."}
        summary_lines = [o.summary_line() for o in obs]
        entities = {k: sorted(v) for k, v in agent._memory.entities.items() if v}
        return {
            "summary": "\n".join(summary_lines),
            "entities_found": entities,
            "tools_used": sorted(agent._memory.tools_used),
            "total_tokens": agent._memory.tokens_used,
        }

    def _refine_query(**kwargs: Any) -> dict[str, Any]:
        """Rephrase a semantic search query for better vector recall."""
        original = kwargs.get("query", "")
        context = kwargs.get("context", "")
        alternatives = [
            original,
            f"anomaly detection {original}",
            f"security incident {original}",
        ]
        if context:
            alternatives.append(f"{original} {context}")
        return {
            "original": original,
            "refined_queries": alternatives,
            "suggestion": alternatives[1] if len(alternatives) > 1 else original,
        }

    def _ask_clarification(**kwargs: Any) -> dict[str, Any]:
        """Return a clarifying question to the user."""
        question = kwargs.get("question", "Could you clarify your question?")
        options = kwargs.get("options", [])
        return {
            "clarification_needed": True,
            "question": question,
            "options": options,
        }

    registry.register(
        ToolSpec(
            name="summarize_results",
            description="Compress all observations collected so far into a concise summary with entities and tool usage stats.",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=_summarize_results,
            estimated_tokens=200,
            read_only=True,
            source_label="Agent",
            display_name="Summarize Collected Results",
        )
    )

    registry.register(
        ToolSpec(
            name="refine_query",
            description="Rephrase a search query to improve vector similarity recall. Returns alternative phrasings.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The original search query to refine"},
                    "context": {"type": "string", "description": "Optional context to incorporate"},
                },
                "required": ["query"],
            },
            handler=_refine_query,
            estimated_tokens=100,
            read_only=True,
            source_label="Agent",
            display_name="Refine Search Query",
        )
    )

    registry.register(
        ToolSpec(
            name="ask_clarification",
            description="Ask the user a clarifying question when the query is ambiguous. Use sparingly.",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The clarifying question to ask"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of suggested answers",
                    },
                },
                "required": ["question"],
            },
            handler=_ask_clarification,
            estimated_tokens=50,
            read_only=True,
            source_label="Agent",
            display_name="Ask Clarification Question",
        )
    )
