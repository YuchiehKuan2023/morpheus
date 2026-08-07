import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Anchor .env lookup to the repo root (dfp-demo/.env), regardless of CWD.
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_file)

# Add project root to sys.path so shared modules (scripts.constants, modules.*)
# are importable from the backend server context.
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from routes import (  # noqa: E402
    anomalies_router,
    auth_router,
    chat_router,
    dashboard_router,
    forecast_router,
    graph_router,
    notifications_router,
    retrain_router,
    simulation_router,
    users_router,
)
from simulation.stage_tracker import recover_orphaned_sessions  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dedicated file handler for agentic AI logs
_agent_log_dir = Path(__file__).resolve().parent.parent.parent / "data" / "logs"
_agent_log_dir.mkdir(parents=True, exist_ok=True)
_agent_handler = logging.FileHandler(_agent_log_dir / "agentic-ai.log", encoding="utf-8")
_agent_handler.setLevel(logging.DEBUG)
_agent_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
for _ns in ("modules.ai.conversational",):
    _lg = logging.getLogger(_ns)
    _lg.addHandler(_agent_handler)
    _lg.setLevel(logging.DEBUG)

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

logger.info(f"Starting API in {ENVIRONMENT} mode")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Recover sessions whose tracker threads were killed by a previous restart.
    recovered = recover_orphaned_sessions()
    if recovered:
        logger.info("Startup: recovered %d orphaned simulation session(s)", recovered)
    yield


app = FastAPI(
    title="DFP Demo API",
    description="API for Digital Fingerprinting Platform Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(anomalies_router, prefix="/api/v1/anomalies", tags=["anomalies"])
app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
app.include_router(simulation_router, prefix="/api/v1/simulation", tags=["simulation"])
app.include_router(graph_router, prefix="/api/v1/graph", tags=["graph"])
app.include_router(chat_router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(notifications_router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(retrain_router, prefix="/api/v1/retrain", tags=["retrain"])
app.include_router(forecast_router, prefix="/api/v1/forecast", tags=["forecast"])


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/")
def root():
    return {"message": "DFP Demo API", "docs": "/docs", "health": "/api/health"}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8001"))
    log_level = os.getenv("LOG_LEVEL", "info")

    uvicorn.run(app, host=host, port=port, log_level=log_level)
