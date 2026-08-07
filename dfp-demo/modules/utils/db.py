"""
Shared PostgreSQL connection utilities.

**Single source of truth** for database connection parameters throughout
the entire ``dfp-demo`` project.  Every script, module, route, and test
should import from here instead of hardcoding ``os.getenv("POSTGRES_*")``
calls.

Usage — connection params dict::

    from modules.utils.db import get_db_params
    conn = psycopg2.connect(**get_db_params())

Usage — context-managed connection::

    from modules.utils.db import get_db
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")

Usage — libpq URL::

    from modules.utils.db import get_db_url
    engine = create_engine(get_db_url())
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

import psycopg2


def get_db_params() -> dict[str, Any]:
    """Return a ``psycopg2.connect()``-compatible dict from env vars.

    Environment variables (all have sensible defaults for local dev):

    - ``POSTGRES_HOST``     — default ``localhost``
    - ``POSTGRES_PORT``     — default ``5433``
    - ``POSTGRES_DB``       — default ``dfp_ai``
    - ``POSTGRES_USER``     — default ``dfp_ai``
    - ``POSTGRES_PASSWORD`` — default ``""``
    """
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5433")),
        "dbname": os.getenv("POSTGRES_DB", "dfp_ai"),
        "user": os.getenv("POSTGRES_USER", "dfp_ai"),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
    }


def get_db_url() -> str:
    """Return a libpq connection URL built from the same env vars."""
    p = get_db_params()
    return f"postgresql://{p['user']}:{p['password']}@{p['host']}:{p['port']}/{p['dbname']}"


@contextmanager
def get_db():
    """Yield a ``psycopg2`` connection; close it when the block exits."""
    conn = psycopg2.connect(**get_db_params())
    try:
        yield conn
    finally:
        conn.close()
