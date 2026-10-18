"""Resolución y validación de olas."""

from functools import lru_cache

from fastapi import HTTPException

from db_runtime import get_conn
from repositories import survey_repository


@lru_cache(maxsize=1)
def wave_ids() -> frozenset[str]:
    """All wave_ids present in the database (for validation)."""
    with get_conn() as conn:
        return frozenset(survey_repository.fetch_wave_ids(conn))


@lru_cache(maxsize=1)
def default_wave() -> str:
    """Devuelve la ola mas reciente. Usado cuando se omite `wave_id`."""
    with get_conn() as conn:
        wave = survey_repository.fetch_latest_wave_id(conn)
    if not wave:
        raise RuntimeError("No waves defined in the database")
    return wave


@lru_cache(maxsize=16)
def categorical_question_ids(wave: str) -> frozenset[str]:
    """q_ids of categorical (non-numeric) questions in a wave."""
    with get_conn() as conn:
        return frozenset(survey_repository.fetch_categorical_question_ids(conn, wave))


@lru_cache(maxsize=1)
def question_catalog() -> dict[tuple[str, str], tuple]:
    """(ola, q_id) → (q_type, concept_id, q_text) de TODAS las olas.

    La base no muta en runtime, así que se lee una vez por proceso en vez de
    consultar el tipo de la pregunta en cada petición.
    """
    with get_conn() as conn:
        rows = survey_repository.fetch_all_questions_with_concept(conn)
    return {
        (wave, q_id): (q_type, concept_id, q_text)
        for wave, q_id, q_type, concept_id, q_text in rows
    }


def resolve_wave(wave: str | None) -> str:
    """Validate an incoming wave_id or fall back to the most recent wave."""
    resolved = wave or default_wave()
    if resolved not in wave_ids():
        raise HTTPException(status_code=400, detail=f"Unknown wave_id: {resolved}")
    return resolved


def list_waves() -> list[dict]:
    """Devuelve las encuestas disponibles. `is_default` marca la ola a cargar."""
    default = default_wave()
    with get_conn() as conn:
        rows = survey_repository.fetch_waves(conn)
    return [
        {
            "wave_id": wave,
            "year": year,
            "label": label,
            "n_respondents": n_respondents,
            "is_default": wave == default,
        }
        for wave, year, label, n_respondents in rows
    ]
