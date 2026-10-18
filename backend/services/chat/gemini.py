"""Adaptador de Gemini: lo único que sabe cuál es el proveedor del modelo.

El SDK (`google.genai`) se importa DENTRO de las funciones a propósito: el modo
IA es opcional y la app debe arrancar en modo manual aunque el paquete no esté
instalado. Confinar esos imports aquí es lo que permite que el resto del
subsistema no tenga que preocuparse por ello.
"""

import logging
import os
import time

from fastapi import HTTPException

import ratelimit

logger = logging.getLogger("encuesta.chat")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GENERATE_RETRIES = 3

_client = None


def is_enabled() -> bool:
    """True si hay API key configurada; si no, la app corre en modo manual."""
    return bool(GEMINI_API_KEY)


def get_client():
    """Cliente de Gemini, creado una sola vez. 503 si falta la API key."""
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="El chat de IA no está disponible.",
            )
        from google import genai

        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def build_config(system_instruction: str, tools: list):
    """Configuración de generación: temperatura 0 para que las cifras no varíen."""
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=tools,
        temperature=0,
    )


def history_to_contents(history):
    """Convierte el historial del front al formato del SDK, ya recortado."""
    from google.genai import types

    contents = []
    for message in ratelimit.trim_history(history or []):
        text = (message.get("text") or "").strip()
        if not text:
            continue
        role = "model" if message.get("role") == "assistant" else "user"
        contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
    return contents


def user_message(text: str):
    """Un turno del usuario en el formato del SDK."""
    from google.genai import types

    return types.Content(role="user", parts=[types.Part(text=text)])


def tool_response_message(parts: list):
    """Las respuestas a las llamadas de herramienta, como un turno más."""
    from google.genai import types

    return types.Content(role="user", parts=parts)


def tool_response_part(name: str, response: dict):
    """El resultado de UNA llamada de herramienta, en el formato del SDK."""
    from google.genai import types

    return types.Part.from_function_response(name=name or "query", response=response)


def is_overloaded(error: Exception) -> bool:
    """True for transient Gemini server overload (503 / UNAVAILABLE)."""
    code = getattr(error, "code", None)
    text = str(error)
    return code == 503 or "UNAVAILABLE" in text or "overloaded" in text.lower()


def generate(client, contents, config):
    """Llama a generate_content, reintentando la saturación transitoria (503)."""
    last_error = None
    for attempt in range(GENERATE_RETRIES):
        try:
            return client.models.generate_content(
                model=GEMINI_MODEL, contents=contents, config=config
            )
        except Exception as error:
            if not is_overloaded(error) or attempt == GENERATE_RETRIES - 1:
                raise
            last_error = error
            delay = 1.5 * (2**attempt)
            logger.warning(
                "Gemini overloaded (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                GENERATE_RETRIES,
                delay,
                error,
            )
            time.sleep(delay)

    if last_error is None:
        raise RuntimeError("generate failed: no exception captured")
    raise last_error


def function_calls_in(response):
    """Las llamadas a herramienta de la respuesta, o [] si sólo hubo texto."""
    candidate = response.candidates[0] if response.candidates else None
    content = candidate.content if candidate else None
    parts = content.parts if content and content.parts else []
    return content, [
        part.function_call for part in parts if getattr(part, "function_call", None)
    ]
