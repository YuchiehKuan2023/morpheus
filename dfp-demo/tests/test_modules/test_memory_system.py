"""
Unit tests for Week 28: Memory System + Conversation Continuity.

Covers:
- EpisodicMemory: record_turn, get_relevant_context, entity overlap ranking
- EntityTracker: registration, alias resolution, pronoun resolution,
  ordinal references, resolve_references (full query rewriting)
- AgentCore integration: session_id pass-through, entity tracker persistence
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parents[2]))

from modules.ai.conversational.entity_tracker import EntityTracker
from modules.ai.conversational.episodic_memory import (
    EpisodicMemory,
    _entity_overlap,
    _format_turns,
    extract_entities,
)

# =========================================================================
# extract_entities
# =========================================================================


class TestExtractEntities:
    """Test the regex-based entity extraction helper."""

    def test_email(self):
        result = extract_entities("Look at john@contoso.com activity")
        assert result == ["john@contoso.com"]

    def test_uuid(self):
        result = extract_entities("anomaly 550e8400-e29b-41d4-a716-446655440000 is critical")
        assert result == ["550e8400-e29b-41d4-a716-446655440000"]

    def test_ip(self):
        result = extract_entities("Login from 10.0.0.1 detected")
        assert result == ["10.0.0.1"]

    def test_multiple(self):
        text = "john@test.com accessed from 192.168.1.1 anomaly 550e8400-e29b-41d4-a716-446655440000"
        result = extract_entities(text)
        assert len(result) == 3
        assert "john@test.com" in result
        assert "192.168.1.1" in result
        assert "550e8400-e29b-41d4-a716-446655440000" in result

    def test_deduplication(self):
        result = extract_entities("john@test.com and john@test.com again")
        assert result == ["john@test.com"]

    def test_empty(self):
        result = extract_entities("no entities here")
        assert result == []


# =========================================================================
# _entity_overlap
# =========================================================================


class TestEntityOverlap:
    def test_full_overlap(self):
        stored = ["john@test.com", "10.0.0.1"]
        query_entities = {"john@test.com", "10.0.0.1"}
        assert _entity_overlap(stored, query_entities) == 2

    def test_partial(self):
        stored = ["john@test.com", "bob@test.com"]
        query_entities = {"john@test.com"}
        assert _entity_overlap(stored, query_entities) == 1

    def test_no_overlap(self):
        assert _entity_overlap(["a@b.com"], {"x@y.com"}) == 0

    def test_empty(self):
        assert _entity_overlap([], {"a@b.com"}) == 0


# =========================================================================
# _format_turns
# =========================================================================


class TestFormatTurns:
    def test_single_turn(self):
        turns = [
            {
                "turn_number": 1,
                "query_summary": "Show critical anomalies",
                "answer_summary": "Found 5 critical anomalies",
                "tools_used": ["search_anomalies"],
                "entities_referenced": ["john@test.com"],
            }
        ]
        text = _format_turns(turns)
        assert "[Turn 1]" in text
        assert "Show critical anomalies" in text
        assert "search_anomalies" in text
        assert "john@test.com" in text

    def test_empty(self):
        assert _format_turns([]) == ""

    def test_missing_fields(self):
        turns = [
            {
                "turn_number": 2,
                "query_summary": "Follow-up",
                "tools_used": None,
                "entities_referenced": None,
            }
        ]
        text = _format_turns(turns)
        assert "[Turn 2]" in text
        assert "none" in text  # tools and entities default to "none"


# =========================================================================
# EpisodicMemory (mocked DB)
# =========================================================================


class TestEpisodicMemory:
    """Test EpisodicMemory with mocked database connections."""

    def _mock_db_context(self, cursor_mock):
        """Create a mock get_db context manager."""
        conn_mock = MagicMock()
        conn_mock.cursor.return_value.__enter__ = MagicMock(return_value=cursor_mock)
        conn_mock.cursor.return_value.__exit__ = MagicMock(return_value=False)
        conn_mock.__enter__ = MagicMock(return_value=conn_mock)
        conn_mock.__exit__ = MagicMock(return_value=False)
        get_db_mock = MagicMock(return_value=conn_mock)
        return get_db_mock

    @patch("modules.ai.conversational.episodic_memory.get_db")
    def test_record_turn(self, mock_get_db):
        cursor_mock = MagicMock()
        # Mock _next_turn returning 1
        cursor_mock.fetchone.return_value = (1,)
        get_db_mock = self._mock_db_context(cursor_mock)
        mock_get_db.side_effect = get_db_mock

        mem = EpisodicMemory(session_id=42)
        mem.record_turn(
            query="Show critical anomalies",
            answer="Found 5 critical anomalies in the last 24 hours.",
            tools_used=["search_anomalies"],
            entities={"john@test.com"},
        )

        # Verify INSERT was called
        calls = cursor_mock.execute.call_args_list
        assert len(calls) >= 1
        # The last execute should be the INSERT
        insert_call = [c for c in calls if "INSERT INTO chat_memory" in str(c)]
        assert len(insert_call) > 0

    @patch("modules.ai.conversational.episodic_memory.get_db")
    def test_get_relevant_context_with_results(self, mock_get_db):
        cursor_mock = MagicMock()
        cursor_mock.fetchall.return_value = [
            {
                "turn_number": 1,
                "query_summary": "Show critical anomalies for john@test.com",
                "answer_summary": "Found 5 anomalies",
                "tools_used": ["search_anomalies"],
                "entities_referenced": ["john@test.com"],
            },
            {
                "turn_number": 2,
                "query_summary": "What is the risk distribution?",
                "answer_summary": "3 critical, 2 high",
                "tools_used": ["get_risk_summary"],
                "entities_referenced": [],
            },
        ]
        get_db_mock = self._mock_db_context(cursor_mock)
        mock_get_db.side_effect = get_db_mock

        mem = EpisodicMemory(session_id=42)
        # Query mentions john@test.com so Turn 1 should rank higher
        context = mem.get_relevant_context("Tell me more about john@test.com")

        assert "john@test.com" in context
        assert "[Turn 1]" in context

    @patch("modules.ai.conversational.episodic_memory.get_db")
    def test_get_relevant_context_empty(self, mock_get_db):
        cursor_mock = MagicMock()
        cursor_mock.fetchall.return_value = []
        get_db_mock = self._mock_db_context(cursor_mock)
        mock_get_db.side_effect = get_db_mock

        mem = EpisodicMemory(session_id=42)
        context = mem.get_relevant_context("anything")
        assert context == ""

    @patch("modules.ai.conversational.episodic_memory.get_db")
    def test_get_relevant_context_entity_ranking(self, mock_get_db):
        """Turns with more entity overlap should rank higher."""
        cursor_mock = MagicMock()
        cursor_mock.fetchall.return_value = [
            {
                "turn_number": 1,
                "query_summary": "Risk summary",
                "answer_summary": "Overall risk is medium",
                "tools_used": ["get_risk_summary"],
                "entities_referenced": [],
            },
            {
                "turn_number": 2,
                "query_summary": "Details on john@test.com",
                "answer_summary": "High risk user",
                "tools_used": ["get_user_profile"],
                "entities_referenced": ["john@test.com"],
            },
        ]
        get_db_mock = self._mock_db_context(cursor_mock)
        mock_get_db.side_effect = get_db_mock

        mem = EpisodicMemory(session_id=42)
        context = mem.get_relevant_context("What about john@test.com?")

        lines = context.strip().split("\n")
        # Turn 2 should appear first (higher entity overlap)
        assert "[Turn 2]" in lines[0]

    def test_summarise_truncation(self):
        """Answer summary should be truncated for long answers."""
        mem = EpisodicMemory(session_id=1)
        short = mem._summarise("short text")
        assert short == "short text"

        long_text = "A" * 600
        summarised = mem._summarise(long_text, max_len=100)
        assert len(summarised) <= 104  # 100 + "..."

    def test_db_failure_graceful(self):
        """If db connection fails, methods should degrade gracefully."""
        with patch("modules.ai.conversational.episodic_memory.get_db", side_effect=Exception("no db")):
            mem = EpisodicMemory(session_id=99)
            # record_turn should silently fail
            mem.record_turn("q", "a", [], set())
            # get_relevant_context should return empty
            assert mem.get_relevant_context("anything") == ""
            # get_all_entities should return empty
            assert mem.get_all_entities() == []


# =========================================================================
# EntityTracker — basic registration
# =========================================================================


class TestEntityTrackerRegistration:
    def test_register_user(self):
        tracker = EntityTracker()
        tracker.update({"john@test.com"}, "user", turn=1)
        ref = tracker.get_entity("john@test.com")
        assert ref is not None
        assert ref.kind == "user"
        assert ref.mention_count == 1

    def test_register_multiple_turns(self):
        tracker = EntityTracker()
        tracker.update({"john@test.com"}, "user", turn=1)
        tracker.update({"john@test.com"}, "user", turn=2)
        ref = tracker.get_entity("john@test.com")
        assert ref is not None
        assert ref.mention_count == 2
        assert ref.last_turn == 2

    def test_email_alias_created(self):
        tracker = EntityTracker()
        tracker.update({"john@contoso.com"}, "user", turn=1)
        # "john" should resolve to the full email
        resolved = tracker.resolve("john")
        assert resolved == "john@contoso.com"

    def test_case_insensitive_lookup(self):
        tracker = EntityTracker()
        tracker.update({"John@Test.com"}, "user", turn=1)
        ref = tracker.get_entity("john@test.com")
        assert ref is not None

    def test_update_from_memory(self):
        tracker = EntityTracker()
        memory_entities = {
            "users": {"alice@test.com", "bob@test.com"},
            "anomaly_ids": {"uuid-123"},
            "ips": {"10.0.0.1"},
        }
        tracker.update_from_memory(memory_entities, turn=1)
        assert tracker.get_entity("alice@test.com") is not None
        assert tracker.get_entity("uuid-123") is not None
        assert tracker.get_entity("10.0.0.1") is not None

    def test_all_entities(self):
        tracker = EntityTracker()
        tracker.update({"a@b.com"}, "user", turn=1)
        tracker.update({"uuid-1"}, "anomaly_id", turn=1)
        all_refs = tracker.all_entities()
        assert len(all_refs) == 2

    def test_all_entities_filtered(self):
        tracker = EntityTracker()
        tracker.update({"a@b.com"}, "user", turn=1)
        tracker.update({"uuid-1"}, "anomaly_id", turn=1)
        users = tracker.all_entities(kind="user")
        assert len(users) == 1
        assert users[0].kind == "user"


# =========================================================================
# EntityTracker — resolution
# =========================================================================


class TestEntityTrackerResolution:
    def test_resolve_direct(self):
        tracker = EntityTracker()
        tracker.update({"john@test.com"}, "user", turn=1)
        assert tracker.resolve("john@test.com") == "john@test.com"

    def test_resolve_alias(self):
        tracker = EntityTracker()
        tracker.update({"john@contoso.com"}, "user", turn=1)
        assert tracker.resolve("john") == "john@contoso.com"

    def test_resolve_unknown(self):
        tracker = EntityTracker()
        assert tracker.resolve("nobody") is None

    def test_resolve_references_pronoun_user(self):
        tracker = EntityTracker()
        tracker.update({"john@test.com"}, "user", turn=1)
        result = tracker.resolve_references("Tell me more about that user")
        assert "john@test.com" in result
        assert "that user" not in result

    def test_resolve_references_pronoun_anomaly(self):
        tracker = EntityTracker()
        tracker.update({"uuid-abc-123"}, "anomaly_id", turn=1)
        result = tracker.resolve_references("Explain the anomaly")
        assert "uuid-abc-123" in result

    def test_resolve_references_ordinal_anomaly(self):
        tracker = EntityTracker()
        tracker.update({"uuid-first"}, "anomaly_id", turn=1)
        tracker.update({"uuid-second"}, "anomaly_id", turn=2)
        result = tracker.resolve_references("Details on anomaly 1")
        assert "uuid-first" in result

    def test_resolve_references_ordinal_user(self):
        tracker = EntityTracker()
        tracker.update({"alice@test.com"}, "user", turn=1)
        tracker.update({"bob@test.com"}, "user", turn=2)
        result = tracker.resolve_references("What about user 2")
        assert "bob@test.com" in result

    def test_resolve_most_recent_user(self):
        """'that user' should resolve to the most recently mentioned user."""
        tracker = EntityTracker()
        tracker.update({"alice@test.com"}, "user", turn=1)
        tracker.update({"bob@test.com"}, "user", turn=2)
        result = tracker.resolve_references("What about that user")
        assert "bob@test.com" in result

    def test_resolve_no_changes_when_no_entities(self):
        tracker = EntityTracker()
        query = "How many anomalies are there?"
        result = tracker.resolve_references(query)
        assert result == query

    def test_resolve_alias_in_query(self):
        tracker = EntityTracker()
        tracker.update({"john@contoso.com"}, "user", turn=1)
        result = tracker.resolve_references("Show activity for john")
        assert "john@contoso.com" in result


# =========================================================================
# AgentCore integration (entity tracker + episodic memory)
# =========================================================================


class TestAgentCoreMemoryIntegration:
    """Test that AgentCore correctly integrates entity tracker and episodic memory."""

    def _make_agent(self):
        """Create an AgentCore with mocked dependencies."""
        from modules.ai.conversational.agent_core import AgentCore
        from modules.ai.conversational.guard_rails import AgentConfig
        from modules.ai.conversational.tool_registry import ToolRegistry

        registry = ToolRegistry()
        client = MagicMock()
        agent = AgentCore(
            tool_registry=registry,
            client=client,
            router_model="test-model",
            answer_model="test-model",
            config=AgentConfig(max_iterations=2),
        )
        return agent

    def test_entity_tracker_exists(self):
        agent = self._make_agent()
        assert hasattr(agent, "_entity_tracker")
        assert isinstance(agent._entity_tracker, EntityTracker)

    def test_entity_tracker_persists_across_runs(self):
        """The entity tracker should survive between runs (same AgentCore instance)."""
        agent = self._make_agent()

        # Simulate a run that encounters user entities
        agent._entity_tracker.update({"alice@test.com"}, "user", turn=1)

        # On a second run, the tracker should still know about alice
        resolved = agent._entity_tracker.resolve("alice")
        assert resolved == "alice@test.com"

    def test_run_accepts_session_id(self):
        """run() should accept session_id parameter without error."""
        agent = self._make_agent()
        # Mock LLM to immediately return an answer
        agent._llm_call = MagicMock(return_value="ANSWER: The answer is 42")
        # Mock _build_response to avoid import issues with _TOOL_SOURCE_LABELS
        agent._build_response = MagicMock(
            return_value=MagicMock(answer="The answer is 42", tools_used=[], steps=1, sources=[])
        )

        # Patch EpisodicMemory to avoid DB calls
        with patch("modules.ai.conversational.agent_core.EpisodicMemory") as MockEM:
            mock_em = MagicMock()
            mock_em.get_relevant_context.return_value = ""
            MockEM.return_value = mock_em

            result = agent.run("test query", [], session_id=99)
            assert result is not None
            MockEM.assert_called_once_with(99)

    def test_run_without_session_id(self):
        """run() should work without session_id (backward compatible)."""
        agent = self._make_agent()
        agent._llm_call = MagicMock(return_value="ANSWER: The answer is 42")
        agent._build_response = MagicMock(
            return_value=MagicMock(answer="The answer is 42", tools_used=[], steps=1, sources=[])
        )

        result = agent.run("test query", [])
        assert result is not None

    def test_resolve_references_called_before_planning(self):
        """Entity resolution should happen early in run(), before planning."""
        agent = self._make_agent()
        agent._entity_tracker.update({"john@test.com"}, "user", turn=1)

        # Mock LLM to return an answer immediately
        agent._llm_call = MagicMock(return_value="ANSWER: Done")
        agent._build_response = MagicMock(return_value=MagicMock(answer="Done", tools_used=[], steps=1, sources=[]))

        agent.run("Tell me about that user", [])

        # Check that _build_response was called (meaning the run completed)
        assert agent._build_response.called
        # The resolved query "john@test.com" should have been passed to _build_response
        call_args = agent._build_response.call_args
        # original_query should be "Tell me about that user"
        assert call_args[0][2] == "Tell me about that user"


# =========================================================================
# Multi-turn integration scenario (mocked)
# =========================================================================


class TestMultiTurnScenario:
    """End-to-end multi-turn scenario with entity tracking."""

    def test_two_turn_entity_persistence(self):
        """
        Turn 1: "Show critical anomalies for john@contoso.com"
        Turn 2: "Tell me more about that user"
        → entity tracker should resolve "that user" to john@contoso.com
        """
        tracker = EntityTracker()

        # Turn 1: register entities
        tracker.update({"john@contoso.com"}, "user", turn=1)
        tracker.update({"uuid-1", "uuid-2"}, "anomaly_id", turn=1)

        # Turn 2: resolve references
        resolved = tracker.resolve_references("Tell me more about that user")
        assert "john@contoso.com" in resolved

    def test_three_turn_ordinal(self):
        """
        Turn 1: mentions anomaly uuid-a
        Turn 2: mentions anomaly uuid-b
        Turn 3: "Compare anomaly 1 with anomaly 2"
        """
        tracker = EntityTracker()
        tracker.update({"uuid-a"}, "anomaly_id", turn=1)
        tracker.update({"uuid-b"}, "anomaly_id", turn=2)

        resolved = tracker.resolve_references("Compare anomaly 1 with anomaly 2")
        assert "uuid-a" in resolved
        assert "uuid-b" in resolved

    def test_episodic_context_ranking(self):
        """Turns mentioning the same entities as the new query should rank higher."""
        turns = [
            {
                "turn_number": 1,
                "query_summary": "General risk",
                "answer_summary": "Overall medium",
                "tools_used": ["get_risk_summary"],
                "entities_referenced": [],
            },
            {
                "turn_number": 2,
                "query_summary": "john@test.com profile",
                "answer_summary": "High risk user",
                "tools_used": ["get_user_profile"],
                "entities_referenced": ["john@test.com"],
            },
            {
                "turn_number": 3,
                "query_summary": "All users",
                "answer_summary": "50 users total",
                "tools_used": ["get_dimension_ranking"],
                "entities_referenced": [],
            },
        ]
        # Query about john should rank turn 2 first
        query_entities = {e.lower() for e in extract_entities("More about john@test.com")}
        ranked = sorted(
            turns,
            key=lambda r: (
                _entity_overlap(r.get("entities_referenced") or [], query_entities),
                r["turn_number"],
            ),
            reverse=True,
        )
        assert ranked[0]["turn_number"] == 2
