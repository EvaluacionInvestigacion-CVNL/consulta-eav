"""Endpoints del modo IA."""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import ratelimit
from services.chat import gemini
from services.chat.conversation import run_chat

logger = logging.getLogger("encuesta.chat")

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


def _friendly_error(error: Exception) -> tuple[int, str]:
    """Map a Gemini/SDK exception to (status_code, user-facing message)."""
    code = getattr(error, "code", None)
    text = str(error)
    if code == 429 or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower():
        return 429, (
            "Se alcanzó el límite de solicitudes. Espera un "
            "momento e intenta de nuevo."
        )
    if code in (401, 403) or "API key" in text or "PERMISSION_DENIED" in text:
        return (
            502,
            "Problema de autenticación con la API de Gemini. Revisa GEMINI_API_KEY.",
        )
    if gemini.is_overloaded(error):
        return 503, (
            "El modelo de IA está temporalmente saturado por alta demanda. "
            "Espera unos segundos e intenta de nuevo."
        )
    return 502, "El asistente no pudo procesar la solicitud. Intenta de nuevo."


@router.post("/chat")
async def chat(req: ChatRequest, request: Request):
    """Responde una pregunta en lenguaje natural consultando la encuesta."""
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="El mensaje está vacío.")
    if len(message) > ratelimit.CHAT_MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El mensaje es demasiado largo (máx "
                f"{ratelimit.CHAT_MAX_MESSAGE_CHARS} caracteres). Acórtalo."
            ),
        )
    # Controles de abuso ANTES de gastar cuota de Gemini.
    try:
        ratelimit.check_and_consume(ratelimit.client_ip(request))
    except ratelimit.RateLimited as error:
        headers = {"X-RateLimit-Scope": error.scope}
        if error.retry_after:
            headers["Retry-After"] = str(error.retry_after)
        raise HTTPException(status_code=429, detail=error.message, headers=headers)
    # El SDK de Gemini es bloqueante: fuera del event loop.
    try:
        return await run_in_threadpool(run_chat, message, req.history)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("chat failed")
        status, detail = _friendly_error(error)
        raise HTTPException(status_code=status, detail=detail)


@router.get("/chat/health")
def chat_health():
    """Si el modo IA está habilitado en este despliegue, y con qué modelo."""
    return {"enabled": gemini.is_enabled(), "model": gemini.GEMINI_MODEL}
