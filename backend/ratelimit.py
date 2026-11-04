"""
Controles de abuso en memoria para el endpoint del chat de IA (POST /api/chat).
"""

import os
import threading
import time
from datetime import date

# --- Config
CHAT_RATE_PER_MIN = int(os.getenv("CHAT_RATE_PER_MIN", "5"))
CHAT_DAILY_GLOBAL = int(os.getenv("CHAT_DAILY_GLOBAL", "15"))
CHAT_MAX_MESSAGE_CHARS = int(os.getenv("CHAT_MAX_MESSAGE_CHARS", "1000"))
CHAT_MAX_HISTORY_MSGS = int(os.getenv("CHAT_MAX_HISTORY_MSGS", "12"))

_WINDOW_SECONDS = 60.0

_lock = threading.Lock()
_ip_hits: dict[str, list[float]] = {}
_global_day: date | None = None
_global_count = 0


class RateLimited(Exception):
    """Se alcanzó un límite. `scope` es 'ip' o 'global'; `retry_after` son
    segundos hasta reintentar (None = vuelve otro día)."""

    def __init__(self, scope: str, message: str, retry_after: int | None):
        super().__init__(message)
        self.scope = scope
        self.message = message
        self.retry_after = retry_after


def reset() -> None:
    """Limpia todos los contadores (solo para tests)."""
    global _global_day, _global_count
    with _lock:
        _ip_hits.clear()
        _global_day = None
        _global_count = 0


def client_ip(request) -> str:
    """IP del cliente detrás del proxy de Render."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_and_consume(ip: str, now: float | None = None) -> None:
    """Registra un request del chat para `ip`, o lanza RateLimited.

    Revisa primero la ventana por IP  y luego el
    presupuesto global diario. Consume de ambos SOLO si ambos pasan, así un
    request rechazado nunca gasta la cuota compartida."""
    now = time.time() if now is None else now
    today = date.fromtimestamp(now)
    with _lock:
        hits = [t for t in _ip_hits.get(ip, []) if now - t < _WINDOW_SECONDS]
        if len(hits) >= CHAT_RATE_PER_MIN:
            # `hits` puede estar vacío si CHAT_RATE_PER_MIN == 0 (chat deshabilitado).
            retry = int(_WINDOW_SECONDS - (now - hits[0])) + 1 if hits else int(_WINDOW_SECONDS)
            raise RateLimited(
                "ip",
                f"Agotaste tus {CHAT_RATE_PER_MIN} consultas por minuto. "
                "Espera un minuto y vuelve a intentarlo.",
                retry,
            )

        global _global_day, _global_count
        if _global_day != today:
            _global_day = today
            _global_count = 0
        if _global_count >= CHAT_DAILY_GLOBAL:
            raise RateLimited(
                "global",
                "El asistente de IA alcanzó su límite de consultas por hoy. "
                "Vuelve mañana, o usa el modo manual mientras tanto.",
                None,
            )

        # Ambos pasaron -> consumir
        hits.append(now)
        _ip_hits[ip] = hits
        _global_count += 1


def trim_history(history: list) -> list:
    """Recorta el historial a las últimas CHAT_MAX_HISTORY_MSGS entradas antes
    de mandarlo al modelo (el frontend lo acumula sin límite)."""
    if not history:
        return []
    if CHAT_MAX_HISTORY_MSGS and len(history) > CHAT_MAX_HISTORY_MSGS:
        return history[-CHAT_MAX_HISTORY_MSGS:]
    return history
