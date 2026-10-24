"""Endpoints de diagnóstico."""

from fastapi import APIRouter

from config import DB_PATH

router = APIRouter(prefix="/api", tags=["diagnóstico"])


@router.get("/health")
def health():
    return {"status": "ok", "db": DB_PATH}


@router.get("/sentry-debug")
def trigger_error():
    division_by_zero = 1 / 0  # noqa: F841
