# DFP Demo — Remaining Work Plan

**Document scope**: What is left to build after March 2026 milestones.
**Reference implementation**: `ai-pir/barclays/` (backend patterns + frontend component patterns).
**Skipped**: Time-series Forecasting (Week 15-16) — deferred until real data.
**Last updated**: May 7, 2026 (Platform hardening + CI/CD + forecasting unblocked)

---

## Summary of Completed Work (as of May 5, 2026)

| Phase    | Milestone                                                        | Status |
| -------- | ---------------------------------------------------------------- | ------ |
| A        | Infrastructure + Synthetic data + Embeddings/NER                 | ✅     |
| B        | Enrichment service, Persistence, LLM, RAG pipeline               | ✅     |
| B Step 4 | AI Orchestrator (dual-thread Kafka consumer)                     | ✅     |
| C        | Auto-labeling Stage 1 + Stage 2 + Risk Scorer + SHAP             | ✅     |
| D W17-20 | Multi-Agent System (Forensics, Investigation, Remediation)       | ✅     |
| D W21-22 | Explainability (LIME, SHAP, confidence, ExplanationTab)          | ✅     |
| D W23    | Authentication + Analyst Review + Status Model                   | ✅     |
| D W24    | Feedback Loop (DFP + Classifier Retraining)                      | ✅     |
| Frontend | Dashboard, Anomalies, Users pages                                | ✅     |
| Frontend | Knowledge Graph page (Track 1)                                   | ✅     |
| Frontend | Conversational AI page (Track 2)                                 | ✅     |
| Frontend | Event Simulator (real-time pipeline visualisation)               | ✅     |
| Frontend | Users — LocationMap + brand icons (Baseline & Detections tabs)   | ✅     |
| Backend  | Orchestrator policy alignment (AI + Agent + Stage Tracker)       | ✅     |
| Backend  | Retrigger endpoint (Mode A repair / Mode B re-publish)           | ✅     |
| Backend  | Anomaly score compression (log-scale, monotone)                  | ✅     |
| DB       | Migrations 001–028, all tables live                              | ✅     |
| Backend  | Authentication (JWT, bcrypt, login/me/logout, permissions)       | ✅     |
| Frontend | Authentication (SignIn, AuthContext, ProtectedRoute, User)       | ✅     |
| Backend  | Analyst Review (assign, review, queue, notifications, feedback)  | ✅     |
| Frontend | Analyst Review (ReviewTab, Notifications, status model update)   | ✅     |
| Frontend | Component refactoring (tabs/, widgets/, named exports)           | ✅     |
| DB       | Status model consolidation (4→3: new/pending/resolved)           | ✅     |
| E W25-30 | Agentic AI (ReAct loop, planning, RAG, memory, streaming)        | ✅     |
| Post-E   | Chat UX refinements + agent quality fixes (May 1–5)              | ✅     |
| Post-E   | Auth simplification — removed SessionExpiredDialog (May 6)       | ✅     |
| Post-E   | Notification auto-assignment + click-to-open dialog (May 6)      | ✅     |
| Post-E   | Anomalies tab pagination + Radix Select dropdowns (May 5–6)      | ✅     |
| Post-E   | Dashboard optimisation — consolidated /snapshot endpoint (May 5) | ✅     |
| CI/CD    | GitHub Actions CI pipeline + Dependabot auto-merge (May 7)       | ✅     |
| Testing  | Agent test suite fixes — 20 tests, 3 production bugs (May 7)     | ✅     |

---

## Remaining Work — Phase E: Agentic AI (Weeks 25–30)

**Design document**: [AGENTIC_AI_INTEGRATION.md](AGENTIC_AI_INTEGRATION.md)

| Week | Focus                                                | Status      |
| ---- | ---------------------------------------------------- | ----------- |
| 25   | Agent Core + Tool Registry + Guard Rails             | ✅ Complete |
| 26   | Planning + Multi-Step Reasoning + Reflector          | ✅ Complete |
| 27   | Advanced RAG (hybrid retrieval, RRF, FTS index)      | ✅ Complete |
| 28   | Memory System (episodic memory, entity tracking)     | ✅ Complete |
| 29   | Frontend (reasoning trace, SSE streaming, metrics)   | ✅ Complete |
| 30   | Hardening, E2E testing, adversarial testing, rollout | ✅ Complete |

### Post-Phase E Refinements (May 1–5, 2026) — ✅ COMPLETE

| Area          | Enhancement                                                                  | Status      |
| ------------- | ---------------------------------------------------------------------------- | ----------- |
| Agent quality | Full answer generation via answer model (SYNTHESIS_PROMPT, 3800 tokens)      | ✅ Complete |
| Agent quality | Router prompt outputs short summary only; synthesis deferred to answer model | ✅ Complete |
| Agent quality | Planner temperature 0.0 for deterministic plans                              | ✅ Complete |
| Agent quality | Planner prompt: mandatory baseline rule, clear tool inclusion guidance       | ✅ Complete |
| Agent quality | Auto-skip pending plan steps when agent finishes early                       | ✅ Complete |
| Agent quality | Humanized observation summaries with tool-specific readable text             | ✅ Complete |
| Agent quality | Tool labels (human-readable names) in backend observations                   | ✅ Complete |
| Agent quality | JSON parsing hardened with `json_repair` library                             | ✅ Complete |
| Streaming     | True SSE streaming via `threading.Thread` + `queue.Queue`                    | ✅ Complete |
| Streaming     | Real-time plan status derivation on client (`useLiveSteps()`)                | ✅ Complete |
| Streaming     | Reasoning trace auto-open during streaming, auto-close when done             | ✅ Complete |
| Chat UX       | Conversation management (archive/delete/rename/export)                       | ✅ Complete |
| Chat UX       | Conversation ID in URL (`/chat/:id`) with page reload persistence            | ✅ Complete |
| Chat UX       | Suggested followup chips with real tool_results context                      | ✅ Complete |
| Chat UX       | Instant scroll (replaced smooth animation)                                   | ✅ Complete |
| Chat UX       | Silent conversation reload after AI completes                                | ✅ Complete |
| Dashboard     | TrendBadge neutral state for 0% delta                                        | ✅ Complete |
| DB            | Migration 028: chat_sessions status + message_count columns                  | ✅ Complete |

---

## ✅ Track 1 — Graph Page (COMPLETE)

**Status**: ✅ COMPLETE (April 20, 2026)
**Priority**: HIGH  
**Effort**: ~3 days  
**Reference**: `ai-pir/barclays/frontend/src/pages/GraphPage.tsx` + `backend/app/api/graph.py`

### What it is

An interactive Neo4j knowledge graph visualisation showing users, detections, and the entities attached to each detection (applications, devices, locations, browsers, operating systems, IPs, and clients). Analysts can click a node to see its details and expand its neighbours. Mirrors the `GraphPage` in the ai-pir project but adapted to the DFP graph schema populated in Neo4j.

### DFP Node Types (already in Neo4j)

- `User` — 17–20 users
- `Detection` — 1,700 detections
- `Application` — 20 apps (e.g. Microsoft Yammer, HubSpot)
- `Device` — 104 devices
- `Location` — 21 locations
- `Browser`
- `OperatingSystem`
- `IPAddress`
- `Client`

### DFP Relationship Types (already in Neo4j)

- `(User)-[:GENERATED]->(Detection)`
- `(Detection)-[:ACCESSED]->(Application)`
- `(Detection)-[:FROM_DEVICE]->(Device)`
- `(Detection)-[:FROM_LOCATION]->(Location)`
- `(Detection)-[:USED_BROWSER]->(Browser)`
- `(Detection)-[:ON_OS]->(OperatingSystem)`
- `(Detection)-[:FROM_IP]->(IPAddress)`
- `(Detection)-[:VIA_CLIENT]->(Client)`

---

### Backend — New route file: `frontend/backend/routes/graph.py`

**Endpoints needed** (pattern from `ai-pir/barclays/backend/app/api/graph.py`):

| Method | Path                                      | Description                                                                                      |
| ------ | ----------------------------------------- | ------------------------------------------------------------------------------------------------ |
| GET    | `/api/v1/graph/stats`                     | Node counts by type + relationship counts by type                                                |
| GET    | `/api/v1/graph/data`                      | Graph nodes + edges for initial render (params: `limit`, `node_types[]`, `relationship_types[]`) |
| GET    | `/api/v1/graph/node/{node_id}`            | Full node detail + its relationships                                                             |
| GET    | `/api/v1/graph/node/{node_id}/neighbours` | Expand a node's immediate connections                                                            |
| GET    | `/api/v1/graph/user/{user_id}/subgraph`   | All connections for a specific user                                                              |
| GET    | `/api/v1/graph/anomaly-clusters`          | High-risk detection cluster (severity=CRITICAL/HIGH)                                             |

**Implementation notes**:

- Use `psycopg2` → NO, use `neo4j` Python driver directly (same as `modules/ai/entity_extraction/graph_populator.py`)
- Import `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` from `os.environ` (already set in `.env`)
- Node IDs: use Neo4j internal node IDs (`id(n)`) as the `{node_id}` identifier for the graph API routes
- For the `/data` endpoint: default `limit=50`, return a mix of Users + connected Detection nodes
- Neo4j session management: open per-request, close in `finally` — mirrors graph_populator pattern
- Register router in `main.py`: `app.include_router(graph_router, prefix="/api/v1/graph")`

---

### Frontend — New page: `frontend/ui/src/pages/Graph.tsx`

**Component tree** (mirrors ai-pir):

```bash
GraphPage
├── GlassCard (stats strip)       — User/Detection/App/Device/Location counts
├── GraphVisualization            — react-force-graph-2d canvas
│   └── GraphLegend               — colour key for node types
├── GraphControls                 — zoom in/out, fit, reset, pause/play
└── NodeDetailPanel (slide-in)    — shown on node click
    ├── node type badge
    ├── node properties
    └── related detections list (for User nodes)
```

**Dependencies to install**:

```bash
npm install react-force-graph-2d
npm install --save-dev @types/react-force-graph-2d
```

> `react-force-graph-2d` is already used in ai-pir — use identical `ForceGraph2D` import pattern.

**Node colour mapping** (DFP-specific):
| Node Type | Colour |

| --- | --- |
| User | `#bef264` (lime-300, brand colour) |
| Detection (CRITICAL) | `#f87171` (red-400) |
| Detection (HIGH) | `#fb923c` (orange-400) |
| Detection (MEDIUM) | `#fcd34d` (amber-300) |
| Application | `#60a5fa` (blue-400) |
| Device | `#a78bfa` (violet-400) |
| Location | `#34d399` (emerald-400) |

**Files to create**:

1. `frontend/ui/src/pages/Graph.tsx` — page component
2. `frontend/ui/src/components/graph/GraphVisualization.tsx` — `ForceGraph2D` canvas with `forwardRef`
3. `frontend/ui/src/components/graph/GraphControls.tsx` — zoom/fit/reset/pause buttons (GlassCard styled)
4. `frontend/ui/src/components/graph/GraphLegend.tsx` — colour legend row
5. `frontend/ui/src/components/graph/NodeDetailPanel.tsx` — slide-in detail panel
6. `frontend/ui/src/services/graph.ts` — API service (copy ai-pir pattern, update base paths)
7. `frontend/ui/src/types/graph.ts` — DFP-specific types (User/Detection/App/Device/Location nodes)
8. `frontend/ui/src/hooks/useGraph.ts` — `useReducer` state: stats, selectedNode, filters, loading

**App.tsx changes** — add route and nav item:

```tsx
// App.tsx — add route
<Route path="graph" element={<Graph />} />

// TopNavigation.tsx — add nav item
{ title: 'Knowledge Graph', href: '/graph', icon: Network }
```

> `Network` is available from `lucide-react`.

---

## ✅ Track 2 — Conversational AI Page (COMPLETE)

**Status**: ✅ COMPLETE (April 25, 2026)
**Priority**: HIGH  
**Effort**: ~4 days  
**Reference**: `ai-pir/barclays/frontend/src/pages/ChatPage.tsx` + `backend/app/api/chat.py` + `backend/app/services/conversational_ai_service.py`

### What it is (chat)

A chat interface where analysts can ask natural language questions about the DFP anomaly data. The chatbot uses two-pass LLM routing (Groq): Pass 1 selects tools, Pass 2 synthesises the answer from tool results. Backed by PostgreSQL, Neo4j, and Qdrant.

### Architecture (mirrors ai-pir exactly)

```bash
Frontend ChatPage
    └── ConversationArea (messages + input)
    └── ChatSidebar (session list + suggested questions)
          │
          │  POST /api/v1/chat/query
          ▼
Backend chat.py router
    └── ConversationalAIService
          ├── Pass 1: GroqService.route_query()  → tool selection
          ├── Pass 2: ExecuteTools (_fetch_* methods)
          └── Pass 3: GroqService.generate_answer() → natural language response
                │
                ├── _fetch_search_anomalies()      → enriched_anomalies (PostgreSQL)
                ├── _fetch_get_anomaly_detail()     → single anomaly + LLM explanation
                ├── _fetch_get_user_profile()       → user anomaly history
                ├── _fetch_get_similar_anomalies()  → Qdrant k-NN
                ├── _fetch_get_neo4j_graph()        → Neo4j entity relationships
                ├── _fetch_get_risk_summary()       → risk band distribution
                ├── _fetch_get_investigation()      → agent findings (agent_findings table)
                └── _fetch_get_top_anomalies()      → top-N by risk score
```

---

### Backend — New route file: `frontend/backend/routes/chat.py`

**Endpoints needed** (pattern from `ai-pir/barclays/backend/app/api/chat.py`):

| Method | Path                         | Description                                         |
| ------ | ---------------------------- | --------------------------------------------------- |
| POST   | `/api/v1/chat/query`         | Process natural language query, return AI answer    |
| GET    | `/api/v1/chat/sessions`      | List all chat sessions (paginated)                  |
| GET    | `/api/v1/chat/sessions/{id}` | Single session with full message history            |
| DELETE | `/api/v1/chat/sessions/{id}` | Delete a session                                    |
| GET    | `/api/v1/chat/suggestions`   | Get suggested questions based on current data state |

**Database**: Chat sessions/messages stored in PostgreSQL. Need new migration:

```sql
-- scripts/db/migrations/013_create_chat_tables.sql
CREATE TABLE chat_sessions (
    id          SERIAL PRIMARY KEY,
    user_id     TEXT,
    title       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE chat_messages (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    intent      TEXT,
    sources     JSONB,
    confidence  FLOAT,
    data        JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_chat_messages_session ON chat_messages(session_id);
CREATE INDEX idx_chat_sessions_updated ON chat_sessions(updated_at DESC);
```

**ConversationalAIService** — New file: `frontend/backend/services/conversational_ai_service.py`

> Model this directly on `ai-pir/barclays/backend/app/services/conversational_ai_service.py` but replace the `Incident`-domain tools with DFP-domain tools.

**DFP-specific tools** (replace ai-pir's CHAT_TOOLS):

```python
CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_anomalies",
            "description": "Search anomalies by severity, user, root cause, or date range.",
            "parameters": { ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_anomaly_detail",
            "description": "Get full AI-enriched detail for a single anomaly by ID, including LLM explanation.",
            "parameters": { "required": ["anomaly_id"], ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": "Get all anomalies for a specific user with risk trend.",
            "parameters": { "required": ["user_id"], ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_similar_anomalies",
            "description": "Find semantically similar anomalies using vector search (Qdrant).",
            "parameters": { "required": ["description"], ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_graph_context",
            "description": "Get Neo4j entity relationships for a user or anomaly.",
            "parameters": { "required": ["entity"], ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_risk_summary",
            "description": "Get risk band distribution and top-N highest risk anomalies.",
            "parameters": {}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_investigation",
            "description": "Get multi-agent investigation findings for an anomaly.",
            "parameters": { "required": ["anomaly_id"], ... }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_root_cause_breakdown",
            "description": "Get distribution of root causes across all anomalies.",
            "parameters": {}
        }
    }
]
```

**GroqService** — Reuse `modules/ai/llm/llm_service.py` (already has `chat()` method). Import it directly:

```python
from modules.ai.llm.llm_service import LLMService
```

**Suggested questions** — dynamically generated based on DB state (top user by risk, most common root cause):

```python
def get_suggested_questions(db_conn) -> list[dict]:
    # Query top user, most common root cause, count of CRITICAL anomalies
    # Return 6 contextual suggestions
```

**Security**: Input validation — max 500 chars, strip HTML, reject SQL patterns. Mirror `ai-pir/barclays/backend/app/utils/security.py::validate_conversational_query()`.

---

### Frontend — New page: `frontend/ui/src/pages/Chat.tsx`

**Component tree** (mirrors ai-pir):

```bash
ChatPage
├── ChatProvider (useReducer context)
├── ChatSidebar (left, fixed width)
│   ├── "New Chat" button
│   ├── session list (scrollable, grouped by date)
│   └── SuggestedQuestions list
└── ConversationArea (right, flex-1)
    ├── WelcomeMessage (shown when messages=[])
    ├── Messages list (scrollable)
    │   ├── UserMessage
    │   └── AIMessage
    │       ├── markdown-rendered answer
    │       ├── IntentBadge
    │       ├── ConfidenceBar
    │       └── SourceList
    └── MessageInput (textarea + send button)
```

**Files to create**:

1. `frontend/ui/src/pages/Chat.tsx` — page with `ChatProvider` + `ChatPageContent`
2. `frontend/ui/src/contexts/ChatContext.tsx` — `useReducer` store for messages/sessions/loading
3. `frontend/ui/src/hooks/useChat.ts` — `useContext(ChatContext)` helper
4. `frontend/ui/src/components/chat/ChatSidebar.tsx` — session list + suggestions
5. `frontend/ui/src/components/chat/ConversationArea.tsx` — messages + input
6. `frontend/ui/src/components/chat/WelcomeMessage.tsx` — empty state (DFP-specific prompts)
7. `frontend/ui/src/components/chat/UserMessage.tsx` — user bubble
8. `frontend/ui/src/components/chat/AIMessage.tsx` — AI bubble with intent/confidence/sources
9. `frontend/ui/src/components/chat/MessageInput.tsx` — textarea + send (with Enter key)
10. `frontend/ui/src/components/chat/IntentBadge.tsx` — maps intent string to coloured badge
11. `frontend/ui/src/components/chat/ConfidenceBar.tsx` — thin progress bar under AI message
12. `frontend/ui/src/components/chat/SourceList.tsx` — chips listing data sources used
13. `frontend/ui/src/components/chat/SuggestedQuestions.tsx` — clickable suggestion pills
14. `frontend/ui/src/services/chat.ts` — `sendQuery()`, `getSessions()`, `getSessionDetail()`, `deleteSession()`, `getSuggestions()`
15. `frontend/ui/src/types/chat.ts` — `ChatMessage`, `ChatSession`, `ConversationalQuery`, `ConversationalResponse`, `SuggestedQuestion`

**DFP-specific WelcomeMessage suggestions**:

- "Show me all CRITICAL anomalies from this week"
- "Which users have the highest risk scores?"
- "What are the most common root causes?"
- "Find anomalies similar to impossible travel attacks"
- "What did the forensics agent find for user alice_smith?"
- "Show me the Neo4j connections for the top anomaly"

**TopNavigation.tsx** — already has `Conversational AI` nav item pointing to `/chat`. Just add the route to `App.tsx`.

---

## ✅ Track 3 — Explainability (COMPLETE)

**Status**: ✅ COMPLETE (April 23, 2026)
**Priority**: MEDIUM  
**Effort**: ~3 days  
**Pre-requisite**: None — the XGBoost risk scorer model + SHAP are already operational  
**Scheduled start**: Can start immediately (SHAP is already computed and stored in `risk_factors` JSONB)

### Assessment

The hardest part (SHAP TreeExplainer + XGBoost integration) is **already done** from Week 11-14:

- `modules/ai/risk_scoring/explainer.py` — SHAP already computed for all 1,652 TPs
- `enriched_anomalies.risk_factors` — stores `{"top_drivers": [...], "top_mitigators": [...], "shap_values": {...}}`

What is NOT done:

- `modules/ai/explainability/lime_explainer.py` — LIME local approximation (new)
- `modules/ai/explainability/confidence_scorer.py` — ensemble confidence (DFP + LLM + risk scorer)
- Frontend "Explanation" tab on AnomalyDetail sheet

### Effort estimate (honest)

| Component                                                 | Effort      |
| --------------------------------------------------------- | ----------- |
| `lime_explainer.py`                                       | 4h          |
| `confidence_scorer.py`                                    | 2h          |
| Backend endpoint (read SHAP from DB + compute confidence) | 2h          |
| Frontend: SHAP waterfall chart                            | 4h          |
| Frontend: confidence ring + LIME bar chart                | 3h          |
| Frontend: AnomalyDetail sheet/drawer                      | 4h          |
| Testing                                                   | 2h          |
| **Total**                                                 | **~3 days** |

**Recommendation**: Since SHAP is already stored in the DB, the backend work is essentially just an API endpoint to expose it. The main effort is the frontend chart components. This is worth doing — it directly differentiates the PoC and gives analysts trust in the AI scores.

### Backend additions needed

- `frontend/backend/routes/anomalies.py` — extend `GET /api/v1/anomalies/{id}` to include `risk_factors` JSONB
- `frontend/backend/services/explainability_service.py` — `get_explanation(anomaly_id)` reads SHAP from DB + computes confidence score
- New endpoint: `GET /api/v1/anomalies/{id}/explanation` — returns SHAP values + LIME weights + confidence

### Frontend additions needed

- `frontend/ui/src/pages/Anomalies.tsx` — clicking an anomaly opens an `AnomalyDetail` sheet/drawer
- `frontend/ui/src/components/anomalies/AnomalyDetailSheet.tsx` — tabbed panel (Overview / Explanation / Investigation)
- `frontend/ui/src/components/anomalies/SHAPChart.tsx` — horizontal bar chart, positive=red, negative=green
- `frontend/ui/src/components/anomalies/ConfidenceRing.tsx` — circular SVG progress with breakdown tooltip
- `frontend/ui/src/components/anomalies/InvestigationPanel.tsx` — shows agent findings (calls `/api/v1/anomalies/{id}/investigation`)

---

## ✅ Track 4 — Live End-to-End Integration Test (Pipeline Validation) — COMPLETE

**Status**: ✅ COMPLETE (tested extensively, progress tracker not updated in time)

```bash
# 1. Start all services
./services/start_services.sh

# 2. Start AI orchestrator
python scripts/run_ai_orchestrator.py &

# 3. Push one synthetic event through Kafka
kafka-console-producer --bootstrap-server 127.0.0.1:29092 --topic dfp-events \
    < data/input/test_normal_event.json

# 4. Verify enriched_anomalies row
psql -U $POSTGRES_USER -d $POSTGRES_DB -c "
SELECT anomaly_id, user_id, anomaly_score, root_cause, risk_score, validated_at
FROM enriched_anomalies
ORDER BY created_at DESC LIMIT 3;"

# 5. Start agent orchestrator (triggers on HIGH/CRITICAL)
python scripts/run_agent_orchestrator.py &

# 6. Verify agent_investigations row (if event was HIGH/CRITICAL)
psql -U $POSTGRES_USER -d $POSTGRES_DB -c "
SELECT i.investigation_id, i.status, i.confidence_score,
       COUNT(f.finding_id) as findings
FROM agent_investigations i
LEFT JOIN agent_findings f ON f.investigation_id = i.investigation_id
GROUP BY 1,2,3
ORDER BY i.triggered_at DESC LIMIT 3;"
```

---

## Implementation Order

| Week              | Track                | Deliverable                                                                      | Status |
| ----------------- | -------------------- | -------------------------------------------------------------------------------- | ------ |
| ~~Track 4~~       | ~~Pipeline test~~    | End-to-end pipeline validation                                                   | ✅     |
| ~~Track 1~~       | ~~Graph Page~~       | Neo4j knowledge graph visualisation                                              | ✅     |
| ~~Apr 20-23~~     | ~~UI Polish~~        | LocationMap coords fix, BrandGraphList, UserDialog refactor                      | ✅     |
| ~~Track 3~~       | ~~Explainability~~   | LIME, SHAP, confidence, ExplanationTab                                           | ✅     |
| ~~Apr 23-25~~     | ~~Track 2 Backend~~  | `routes/chat.py` + `conversational_ai_service.py` + migration 016-017            | ✅     |
| ~~Apr 25-26~~     | ~~Track 2 Frontend~~ | Chat page + ChatInput + ChatSidebar + MessageBubble + SuggestedQuestions         | ✅     |
| ~~Apr 24-26~~     | ~~Event Simulator~~  | Full simulation engine + SSE stream + EventFeed + ProcessList                    | ✅     |
| ~~Apr 26-28~~     | ~~Bug fixes~~        | Orchestrator policy alignment, retrigger endpoint, score compression             | ✅     |
| ~~Apr 28~~        | ~~Week 23 Ph 1-2~~   | Authentication Backend + Frontend (JWT, sign-in, ProtectedRoute, User dropdown)  | ✅     |
| ~~Apr 28-29~~     | ~~Week 23 Ph 3-4~~   | Analyst Review + Notifications + status model + component refactoring            | ✅     |
| **Now (Apr 29+)** | **Week 24**          | **Feedback Loop: DFP autoencoder + classifier retraining (XGBoost, DistilBERT)** | ✅     |
| May 5             | Dashboard            | Consolidated /snapshot endpoint, simulation pagination                           | ✅     |
| May 5–6           | UI Polish            | Anomalies tab pagination, Radix Select, cross-filtered counts                    | ✅     |
| May 6             | Auth                 | Removed SessionExpiredDialog, instant 401 redirect                               | ✅     |
| May 6             | Notifications        | Auto-assignment notifications + click-to-open anomaly detail dialog              | ✅     |
| May 7             | CI/CD                | GitHub Actions CI pipeline + Dependabot auto-merge workflow                      | ✅     |
| May 7             | Testing              | 20 agent test fixes (memory.py, json_parser, mock responses)                     | ✅     |
| May 7             | Forecasting          | Prophet forecaster + feedback loop retraining + API + frontend chart             | ✅     |

---

## What is Explicitly Skipped (per decision)

| Track                                  | Reason                           | Status       |
| -------------------------------------- | -------------------------------- | ------------ |
| ~~Week 15-16 Time Series Forecasting~~ | ~~Requires 500+ real anomalies~~ | ✅ COMPLETED |

### Forecasting — Completed (May 7, 2026)

**Data assessment (May 7, 2026)**:

- **108 real anomalies**: 59 ai_auto_labeler + 48 heuristic_score + 1 pending
- **1,652 synthetic anomalies**: validated_by `heuristic_midband` (from bulk paired-detection ingestion)
- Temporal span: December 16, 2025 – May 6, 2026 (~5 months), 24 users
- Model uses all data initially; **auto-switches to real-only at 500+ real anomalies**

**What was built**:

| Component                                      | Status                                              |
| ---------------------------------------------- | --------------------------------------------------- |
| `modules/ai/forecasting/prophet_forecaster.py` | ✅ Prophet model: train/predict/save/load           |
| Feedback loop integration                      | ✅ `check_and_retrain()` in `run_retrain_runner.py` |
| `GET /api/v1/forecast`                         | ✅ Historical + forecast + 90% CI bands             |
| `POST /api/v1/forecast/retrain`                | ✅ Manual retrain trigger                           |
| `GET /api/v1/forecast/summary`                 | ✅ Data stats + model status                        |
| `ForecastChart.tsx`                            | ✅ Recharts ComposedChart on Dashboard              |
| CLI flags                                      | ✅ `--forecast-only`, `--force-forecast`            |

---

## Reference Files (ai-pir → dfp-demo mapping)

| ai-pir file                                            | dfp-demo equivalent                                      | Notes                                                                                       |
| ------------------------------------------------------ | -------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `frontend/src/pages/GraphPage.tsx`                     | `frontend/ui/src/pages/Graph.tsx`                        | Direct port, change node types                                                              |
| `frontend/src/components/graph/GraphVisualization.tsx` | same path                                                | Direct port                                                                                 |
| `frontend/src/components/graph/NodeDetailPanel.tsx`    | same path                                                | Change incident properties to detection properties                                          |
| `frontend/src/services/graph.ts`                       | same path                                                | Change base URL `VITE_API_URL`                                                              |
| `frontend/src/types/graph.ts`                          | same path                                                | Replace Incident/Organization/RootCause/Domain → User/Detection/Application/Device/Location |
| `frontend/src/pages/ChatPage.tsx`                      | `frontend/ui/src/pages/Chat.tsx`                         | Direct port                                                                                 |
| `frontend/src/components/chat/*`                       | same paths                                               | Direct port — domain-agnostic components                                                    |
| `frontend/src/services/chat.ts`                        | same path                                                | Direct port, same API shape                                                                 |
| `frontend/src/types/chat.ts`                           | same path                                                | Direct port                                                                                 |
| `frontend/src/contexts/ChatContext.tsx`                | same path                                                | Direct port                                                                                 |
| `frontend/src/hooks/useChat.ts`                        | same path                                                | Direct port                                                                                 |
| `backend/app/api/graph.py`                             | `frontend/backend/routes/graph.py`                       | Adapt Cypher for DFP node model                                                             |
| `backend/app/api/chat.py`                              | `frontend/backend/routes/chat.py`                        | Direct port, swap `ConversationalAIService`                                                 |
| `backend/app/services/conversational_ai_service.py`    | `frontend/backend/services/conversational_ai_service.py` | Replace incident tools with anomaly tools                                                   |

---

## Key Integration Points

### Graph backend → DFP Neo4j

The DFP Neo4j graph uses different node labels than ai-pir. The Cypher queries must use:

- `MATCH (u:User)` not `MATCH (o:Organization)`
- `MATCH (d:Detection)` not `MATCH (i:Incident)`
- `MATCH (a:Application)` not `MATCH (r:RootCause)`

Use `modules/ai/entity_extraction/graph_populator.py` as the canonical reference for the exact Neo4j schema.

### Conversational AI backend → DFP data

The `ConversationalAIService._fetch_*` methods must query `enriched_anomalies` (psycopg2 direct, not SQLAlchemy), mirror the connection pattern in `frontend/backend/routes/anomalies.py` using `db.py::get_db()`.

For Qdrant queries (similar anomalies), import `modules.ai.embeddings.similarity_search.SimilaritySearch`.

For Neo4j queries (graph context), connect directly using `neo4j` driver with env vars:

```python
from neo4j import GraphDatabase
driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
```

For Groq LLM routing, import:

```python
from modules.ai.llm.llm_service import LLMService
```

The `chat(system, user, mode)` method is already available.
