"""
Database connection utilities — thin re-export.

All connection logic now lives in :mod:`modules.utils.db`.
This file re-exports ``get_db`` and ``get_db_params`` so that existing
``from db import get_db`` calls inside ``frontend/backend/`` keep working.
"""

from modules.utils.db import get_db, get_db_params  # noqa: F401
