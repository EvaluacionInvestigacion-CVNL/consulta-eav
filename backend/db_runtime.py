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
                # Un hilo por consulta: Render da una fracción de CPU, y los
                # hilos que DuckDB abre por cada núcleo visible sólo compiten
                # por esa cuota. El paralelismo viene de atender varias
                # peticiones a la vez, no de partir cada consulta.
                _database = duckdb.connect(
                    DB_PATH, read_only=True, config={"threads": 1}
                )
    return _database.cursor()
