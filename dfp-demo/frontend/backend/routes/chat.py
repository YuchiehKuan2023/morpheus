import json
import logging
import queue
import threading

from auth_utils import get_current_user
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.conversational_ai_service import DFPConversationalAIService

logger = logging.getLogger(__name__)
router = APIRouter()

# Singleton service instance (initialised lazily on first request)
_service: DFPConversationalAIService | None = None


def _get_service() -> DFPConversationalAIService:
    global _service
    if _service is None:
        try:
            _service = DFPConversationalAIService()
        except (ValueError, RuntimeError) as exc:
            logger.error("Cannot initialise ConversationalAIService: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
    return _service


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    session_id: int
    query: str


class CreateSessionRequest(BaseModel):
    title: str = "New Conversation"


class RenameSessionRequest(BaseModel):
    title: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/sessions")
def create_session(body: CreateSessionRequest, user: dict = Depends(get_current_user)):
    """Create a new chat session."""
    svc = _get_service()
    try:
        return svc.create_session(title=body.title, user_id=user.get("id"))
    except Exception as exc:
        logger.error("create_session error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create session") from exc


@router.get("/sessions")
def list_sessions(
    status: str = Query("active", pattern="^(active|archived)$"),
    user: dict = Depends(get_current_user),
):
    """Return sessions filtered by status, ordered by most recently active."""
    svc = _get_service()
    try:
        return svc.get_sessions(status=status, user_id=user.get("id"))
    except Exception as exc:
        logger.error("list_sessions error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch sessions") from exc


@router.get("/sessions/{session_id}")
def get_session(session_id: int, user: dict = Depends(get_current_user)):
    """Return a single session with its full message history."""
    svc = _get_service()
    session = svc.get_session(session_id, user_id=user.get("id"))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, user: dict = Depends(get_current_user)):
    """Delete a session and all its messages."""
    svc = _get_service()
    deleted = svc.delete_session(session_id, user_id=user.get("id"))
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True, "session_id": session_id}


@router.post("/sessions/{session_id}/archive")
def archive_session(session_id: int, user: dict = Depends(get_current_user)):
    """Archive a session."""
    svc = _get_service()
    if not svc.archive_session(session_id, user_id=user.get("id")):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"archived": True, "session_id": session_id}


@router.post("/sessions/{session_id}/unarchive")
def unarchive_session(session_id: int, user: dict = Depends(get_current_user)):
    """Restore an archived session."""
    svc = _get_service()
    if not svc.unarchive_session(session_id, user_id=user.get("id")):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"unarchived": True, "session_id": session_id}


@router.patch("/sessions/{session_id}/rename")
def rename_session(session_id: int, body: RenameSessionRequest, user: dict = Depends(get_current_user)):
    """Rename a session."""
    svc = _get_service()
    if not svc.rename_session(session_id, body.title.strip(), user_id=user.get("id")):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"renamed": True, "session_id": session_id, "title": body.title.strip()}


@router.get("/sessions/{session_id}/export")
def export_session(session_id: int, user: dict = Depends(get_current_user)):
    """Export a conversation for download."""
    svc = _get_service()
    data = svc.export_session(session_id, user_id=user.get("id"))
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


@router.post("/query")
def query(body: QueryRequest, user: dict = Depends(get_current_user)):
    """
    Main chat endpoint.

    Runs the two-pass Groq pipeline:
      1. LLM selects which data tools to call (no rule-based intent)
      2. Tools are executed against PostgreSQL / Neo4j
      3. LLM synthesises a grounded natural-language answer

    Returns:
        { answer, tools_used, session_id }
    """
    if not body.query.strip():
        raise HTTPException(status_code=422, detail="Query cannot be empty")

    svc = _get_service()
    if svc.get_session(body.session_id, user_id=user.get("id")) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        return svc.process_query(session_id=body.session_id, query=body.query.strip())
    except Exception as exc:
        logger.error("process_query error (session=%s): %s", body.session_id, exc)
        raise HTTPException(status_code=500, detail="Failed to process query") from exc


@router.get("/suggestions")
def get_suggestions(_user: dict = Depends(get_current_user)):
    """Return dynamic suggested questions based on current platform state."""
    svc = _get_service()
    try:
        return {"suggestions": svc.get_suggested_questions()}
    except Exception as exc:
        logger.error("get_suggestions error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch suggestions") from exc


# ---------------------------------------------------------------------------
# Agent metrics
# ---------------------------------------------------------------------------


@router.get("/agent-metrics")
def get_agent_metrics(_user: dict = Depends(get_current_user)):
    """
    Aggregate agent performance metrics from recent chat messages.

    Returns stats like average steps per query, tool call distribution,
    and latency breakdown derived from persisted reasoning traces.
    """
    import psycopg2.extras
    from db import get_db

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Total agentic queries (messages with reasoning trace data)
                cur.execute(
                    """
                    SELECT COUNT(*) AS total_queries,
                           AVG((data->>'steps')::int) AS avg_steps,
                           MAX((data->>'steps')::int) AS max_steps
                    FROM chat_messages
                    WHERE role = 'assistant' AND data IS NOT NULL AND data ? 'reasoning_trace'
                    """
                )
                summary = dict(cur.fetchone() or {})

                # Tool call distribution (from tools_used JSON array)
                cur.execute(
                    """
                    SELECT tool, COUNT(*) AS call_count
                    FROM chat_messages,
                         jsonb_array_elements_text(tools_used::jsonb) AS tool
                    WHERE role = 'assistant' AND tools_used IS NOT NULL
                    GROUP BY tool
                    ORDER BY call_count DESC
                    LIMIT 20
                    """
                )
                tool_distribution = [dict(r) for r in cur.fetchall()]

                # Recent traces — average elapsed_ms per tool (last 100 messages)
                cur.execute(
                    """
                    SELECT step->>'tool' AS tool,
                           AVG((step->>'elapsed_ms')::int) AS avg_latency_ms,
                           COUNT(*) AS invocations
                    FROM (
                        SELECT jsonb_array_elements(data->'reasoning_trace') AS step
                        FROM chat_messages
                        WHERE role = 'assistant' AND data IS NOT NULL AND data ? 'reasoning_trace'
                        ORDER BY created_at DESC
                        LIMIT 100
                    ) sub
                    WHERE step->>'kind' = 'action' AND step->>'tool' IS NOT NULL
                    GROUP BY step->>'tool'
                    ORDER BY avg_latency_ms DESC
                    """
                )
                tool_latency = [dict(r) for r in cur.fetchall()]

        return {
            "total_queries": summary.get("total_queries", 0),
            "avg_steps": round(float(summary.get("avg_steps") or 0), 1),
            "max_steps": summary.get("max_steps", 0),
            "tool_distribution": tool_distribution,
            "tool_latency": tool_latency,
        }
    except Exception as exc:
        logger.error("agent-metrics error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch agent metrics") from exc


# ---------------------------------------------------------------------------
# SSE streaming query
# ---------------------------------------------------------------------------


@router.post("/query/stream")
def query_stream(body: QueryRequest, user: dict = Depends(get_current_user)):
    """
    Stream reasoning steps as Server-Sent Events in real time,
    then emit the final answer.

    Events:
      - event: step    data: { kind, content, tool, ... }
      - event: answer  data: { answer, tools_used, ... }
    """
    if not body.query.strip():
        raise HTTPException(status_code=422, detail="Query cannot be empty")

    svc = _get_service()
    if svc.get_session(body.session_id, user_id=user.get("id")) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    def _sse_event(event_type: str, data: dict) -> str:
        return f"event: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"

    # Thread-safe queue: the agent pushes steps, the SSE generator yields them.
    step_queue: queue.Queue[dict | None] = queue.Queue()
    result_holder: list[dict] = []  # single-element list to receive the final result

    def _run_agent():
        try:
            result = svc.process_query_streaming(
                session_id=body.session_id,
                query=body.query.strip(),
                step_callback=lambda step: step_queue.put(step),
            )
            result_holder.append(result)
        except Exception as exc:
            logger.error("Streaming query error: %s", exc)
            result_holder.append({"error": str(exc)})
        finally:
            step_queue.put(None)  # sentinel: agent is done

    def event_generator():
        worker = threading.Thread(target=_run_agent, daemon=True)
        worker.start()

        # Yield steps in real time as the agent produces them
        while True:
            step = step_queue.get()
            if step is None:
                break
            yield _sse_event("step", step)

        worker.join(timeout=5)

        # Emit the final answer
        if result_holder:
            result = result_holder[0]
            if "error" in result:
                yield _sse_event("error", {"detail": "Failed to process query"})
            else:
                answer_payload = {k: v for k, v in result.items() if k != "reasoning_trace"}
                yield _sse_event("answer", answer_payload)
        else:
            yield _sse_event("error", {"detail": "No response from agent"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
