"""Shared pytest fixtures.

The backend reads DB_PATH at import time and resolves it relative to its own
working dir, so we pin it to the built database (absolute path) BEFORE
importing `main`, and add backend/ to sys.path so `import main` works from the
repo root.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

os.environ.setdefault("DB_PATH", str(ROOT / "data" / "encuesta_multianual.duckdb"))
sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402  (la app FastAPI vive aquí)
from services.catalog_service import get_questions  # noqa: E402


@pytest.fixture(scope="session")
def client():
    return TestClient(main.app)


@pytest.fixture(scope="session")
def questions():
    return get_questions()


@pytest.fixture(scope="session")
def numeric_qid(questions):
    """A question whose answers are stored as numbers (q_type == 'numerica')."""
    return next(q["q_id"] for q in questions if q["q_type"] == "numerica")


@pytest.fixture(scope="session")
def categorical_qid(questions):
    """A multiple-choice question that has answer options."""
    return next(
        q["q_id"]
        for q in questions
        if q["q_type"] != "numerica" and q["options"]
    )


@pytest.fixture(scope="session")
def city_ids():
    """Two AMM municipality ids (Monterrey, Apodaca) for city-filter tests."""
    from metadata import ID_TO_CITY_NAME

    name_to_id = {name: cid for cid, name in ID_TO_CITY_NAME.items()}
    return {"Monterrey": name_to_id["Monterrey"], "Apodaca": name_to_id["Apodaca"]}
