"""Acceso de sólo lectura al archivo DuckDB."""

import threading

import duckdb

from config import DB_PATH

_database = None
_lock = threading.Lock()


def get_conn():
    """Una conexión de sólo lectura."""
    global _database
    if _database is None:
        with _lock:
            if _database is None:
                _database = duckdb.connect(DB_PATH, read_only=True)
    return _database.cursor()
