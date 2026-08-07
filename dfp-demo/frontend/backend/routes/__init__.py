from .anomalies import router as anomalies_router
from .auth import router as auth_router
from .chat import router as chat_router
from .dashboard import router as dashboard_router
from .forecast import router as forecast_router
from .graph import router as graph_router
from .notifications import router as notifications_router
from .retrain import router as retrain_router
from .simulation import router as simulation_router
from .users import router as users_router

__all__ = [
    "auth_router",
    "dashboard_router",
    "anomalies_router",
    "forecast_router",
    "users_router",
    "simulation_router",
    "graph_router",
    "chat_router",
    "notifications_router",
    "retrain_router",
]
