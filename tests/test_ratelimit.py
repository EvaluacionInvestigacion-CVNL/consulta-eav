"""Tests para los controles de abuso del chat (backend/ratelimit.py).

No llaman a Gemini ni tocan la BD: ejercitan la ventana por IP, el presupuesto
global diario, el recorte de historial y la extracción de IP. Los endpoints que
se prueban aquí rechazan ANTES de llamar a Gemini, así que tampoco gastan cuota.
"""

import pytest

import ratelimit


@pytest.fixture(autouse=True)
def _clean():
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_per_ip_window_blocks_after_limit(monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_RATE_PER_MIN", 3)
    monkeypatch.setattr(ratelimit, "CHAT_DAILY_GLOBAL", 1000)
    t = 1000.0
    for _ in range(3):
        ratelimit.check_and_consume("1.1.1.1", now=t)
    with pytest.raises(ratelimit.RateLimited) as ei:
        ratelimit.check_and_consume("1.1.1.1", now=t)
    assert ei.value.scope == "ip"
    assert ei.value.retry_after and ei.value.retry_after > 0
    assert "Agotaste tus 3 consultas por minuto" in ei.value.message
    assert "Espera un minuto" in ei.value.message


def test_per_ip_window_slides(monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_RATE_PER_MIN", 2)
    monkeypatch.setattr(ratelimit, "CHAT_DAILY_GLOBAL", 1000)
    ratelimit.check_and_consume("2.2.2.2", now=0.0)
    ratelimit.check_and_consume("2.2.2.2", now=1.0)
    with pytest.raises(ratelimit.RateLimited):
        ratelimit.check_and_consume("2.2.2.2", now=2.0)
    # una vez que la ventana rebasa los dos primeros hits, se permite de nuevo
    ratelimit.check_and_consume("2.2.2.2", now=61.0)


def test_separate_ips_are_independent(monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_RATE_PER_MIN", 1)
    monkeypatch.setattr(ratelimit, "CHAT_DAILY_GLOBAL", 1000)
    ratelimit.check_and_consume("a", now=0.0)
    ratelimit.check_and_consume("b", now=0.0)  # otra IP, ok
    with pytest.raises(ratelimit.RateLimited):
        ratelimit.check_and_consume("a", now=0.0)


def test_global_daily_budget(monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_RATE_PER_MIN", 1000)
    monkeypatch.setattr(ratelimit, "CHAT_DAILY_GLOBAL", 3)
    # IPs distintas para que nunca dispare la ventana por IP
    for i in range(3):
        ratelimit.check_and_consume(f"ip{i}", now=100.0)
    with pytest.raises(ratelimit.RateLimited) as ei:
        ratelimit.check_and_consume("ipX", now=100.0)
    assert ei.value.scope == "global"
    assert ei.value.retry_after is None


def test_global_budget_resets_next_day(monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_RATE_PER_MIN", 1000)
    monkeypatch.setattr(ratelimit, "CHAT_DAILY_GLOBAL", 1)
    day1 = 100.0
    day2 = 100.0 + 86400
    ratelimit.check_and_consume("z", now=day1)
    with pytest.raises(ratelimit.RateLimited):
        ratelimit.check_and_consume("z2", now=day1)
    ratelimit.check_and_consume("z3", now=day2)  # nuevo día, resetea


def test_rejected_request_does_not_consume_global(monkeypatch):
    # Con la ventana por IP en 0, el request se rechaza por IP y NO debe gastar
    # presupuesto global (que quedaría disponible para otra IP).
    monkeypatch.setattr(ratelimit, "CHAT_RATE_PER_MIN", 0)
    monkeypatch.setattr(ratelimit, "CHAT_DAILY_GLOBAL", 5)
    with pytest.raises(ratelimit.RateLimited) as ei:
        ratelimit.check_and_consume("a", now=0.0)
    assert ei.value.scope == "ip"
    assert ratelimit._global_count == 0


def test_trim_history(monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_MAX_HISTORY_MSGS", 3)
    hist = [{"role": "user", "text": str(i)} for i in range(10)]
    trimmed = ratelimit.trim_history(hist)
    assert len(trimmed) == 3
    assert trimmed[0]["text"] == "7"  # conserva las últimas 3
    assert ratelimit.trim_history([]) == []


def test_client_ip_prefers_forwarded_for():
    class R:
        headers = {"x-forwarded-for": "9.9.9.9, 10.0.0.1"}
        client = None

    assert ratelimit.client_ip(R()) == "9.9.9.9"


def test_client_ip_falls_back_to_peer():
    class C:
        host = "5.5.5.5"

    class R:
        headers = {}
        client = C()

    assert ratelimit.client_ip(R()) == "5.5.5.5"


# --- Endpoint (rechazan antes de Gemini, no gastan cuota) ------------------
def test_endpoint_rejects_long_message(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_MAX_MESSAGE_CHARS", 10)
    r = client.post("/api/chat", json={"message": "x" * 50})
    assert r.status_code == 400


def test_endpoint_blocks_when_global_budget_exhausted(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_DAILY_GLOBAL", 0)
    ratelimit.reset()
    r = client.post("/api/chat", json={"message": "hola"})
    assert r.status_code == 429
    assert r.json()["detail"] == (
        "El asistente de IA alcanzó su límite de consultas por hoy. "
        "Vuelve mañana, o usa el modo manual mientras tanto."
    )
    assert r.headers["X-RateLimit-Scope"] == "global"
    assert "Retry-After" not in r.headers


def test_endpoint_per_ip_limit_says_scope_and_when_to_retry(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_RATE_PER_MIN", 0)
    r = client.post("/api/chat", json={"message": "hola"})
    assert r.status_code == 429
    assert "Espera un minuto" in r.json()["detail"]
    assert r.headers["X-RateLimit-Scope"] == "ip"
    assert int(r.headers["Retry-After"]) > 0
