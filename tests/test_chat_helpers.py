"""Tests for the pure (non-LLM) helpers of the chat mode.

These never call Gemini — they exercise the argument normalization, the
JSON-safety coercion (the Decimal→float fix that prevented a 502), and the
tool-call executor that wraps run_query.
"""

import json
from decimal import Decimal

import pytest

from services.chat import query_tool


def test_norm_value_scalar_and_list():
    assert query_tool._normalize_value(5) == 5
    assert query_tool._normalize_value([1, "2", 3]) == [1, 2, 3]


def test_norm_city_value_accepts_numeric():
    assert query_tool._normalize_city_value([39, "6"]) == [39, 6]


def test_norm_city_value_rejects_zone_names():
    with pytest.raises(ValueError):
        query_tool._normalize_city_value(["AMM"])


def test_jsonable_coerces_decimals():
    out = query_tool._jsonable({"a": Decimal("5.5"), "b": [Decimal("1"), {"c": Decimal("2.25")}]})
    assert out == {"a": 5.5, "b": [1.0, {"c": 2.25}]}
    json.dumps(out)  # must not raise


def test_exec_query_returns_serializable_summary(categorical_qid):
    result, summary, effective = query_tool.execute({"question_id": categorical_qid})
    assert result is not None
    # the summary is fed back to Gemini as JSON, so it must serialize cleanly
    json.dumps(summary)
    assert summary["question"]["q_id"] == categorical_qid
    # the effective query drives the chat UI card
    assert effective["question_id"] == categorical_qid
    assert effective["año"]


def test_exec_query_numeric_summary_has_no_decimals(numeric_qid):
    _, summary, _ = query_tool.execute({"question_id": numeric_qid, "group_by": "sexo"})
    json.dumps(summary)  # numeric means come back as Decimal from DuckDB → must be coerced


def test_exec_query_city_filter(numeric_qid, city_ids):
    result, summary, _ = query_tool.execute(
        {
            "question_id": numeric_qid,
            "filters": [{"attribute": "city_id", "value": [city_ids["Monterrey"]]}],
            "group_by": "city_id",
        }
    )
    assert result is not None
    group_cols = result["counts"]["columns"][2:-1]
    assert group_cols == ["Monterrey"]


def test_exec_query_bad_question_returns_error(numeric_qid):
    result, summary, effective = query_tool.execute({"question_id": "__does_not_exist__"})
    assert result is None
    assert "error" in summary
    assert effective["question_id"] == "__does_not_exist__"


# --- título de la conversación ------------------------------------------------

import itertools  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from services.chat import conversation, gemini, prompts  # noqa: E402


@pytest.mark.parametrize(
    "text, title, body",
    [
        ("Título: Seguridad en Monterrey\nEn 2025…", "Seguridad en Monterrey", "En 2025…"),
        ('**Título:** "Calidad del aire".\n\nTexto', "Calidad del aire", "Texto"),
        ("El título más común es licenciatura.", None, "El título más común es licenciatura."),
    ],
)
def test_split_title(text, title, body):
    assert conversation.split_title(text) == (title, body)


def _fake_gemini(monkeypatch, reply_text):
    """Sustituye la llamada al modelo: responde `reply_text` sin herramientas y
    guarda la instrucción de sistema que recibió."""
    seen = {}

    def generate(client, contents, config):
        seen["instruction"] = config.system_instruction
        content = SimpleNamespace(parts=[SimpleNamespace(function_call=None, text=reply_text)])
        return SimpleNamespace(candidates=[SimpleNamespace(content=content)], text=reply_text)

    monkeypatch.setattr(gemini, "get_client", lambda: object())
    monkeypatch.setattr(gemini, "generate", generate)
    return seen


def test_first_turn_asks_for_and_returns_a_title(monkeypatch):
    seen = _fake_gemini(monkeypatch, "Título: Ingreso de los hogares\nEn 2025, **13.5%** ahorra.")
    out = conversation.run_chat("¿Les alcanza para ahorrar?", [])
    assert prompts.NEW_CONVERSATION_RULE in seen["instruction"]
    assert out["title"] == "Ingreso de los hogares"
    assert out["reply"] == "En 2025, **13.5%** ahorra."


def test_later_turns_get_no_title_and_never_show_the_line(monkeypatch):
    seen = _fake_gemini(monkeypatch, "Título: Otra cosa\nEn 2022, **11.2%**.")
    history = [{"role": "user", "text": "hola"}, {"role": "assistant", "text": "¡Hola!"}]
    out = conversation.run_chat("¿y en 2022?", history)
    assert prompts.NEW_CONVERSATION_RULE not in seen["instruction"]
    assert out["title"] is None
    assert out["reply"] == "En 2022, **11.2%**."


# --- rondas de herramientas ----------------------------------------------------


def test_last_round_forces_an_answer_and_keeps_every_result(monkeypatch, categorical_qid):
    """Un modelo que nunca deja de consultar: la última ronda va sin
    herramientas, así que redacta con lo que tiene en vez de perder la
    respuesta; `data` trae cada consulta distinta una sola vez."""
    group_bys = itertools.cycle(["answer", "sexo"])  # de la tercera en adelante, repetidas
    seen_modes = []

    def generate(client, contents, config):
        tool_config = config.tool_config
        mode = tool_config.function_calling_config.mode if tool_config else None
        seen_modes.append(mode)
        if mode is not None:
            text = "En 2025, **50%**."
            part = SimpleNamespace(function_call=None, text=text)
            return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))], text=text)
        call = SimpleNamespace(name="query", args={"question_id": categorical_qid, "group_by": next(group_bys)})
        part = SimpleNamespace(function_call=call)
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(role="model", parts=[part]))])

    monkeypatch.setattr(gemini, "get_client", lambda: object())
    monkeypatch.setattr(gemini, "generate", generate)
    monkeypatch.setattr(conversation.gemini, "tool_response_part", lambda name, response: response)
    monkeypatch.setattr(conversation.gemini, "tool_response_message", lambda parts: parts)

    out = conversation.run_chat("algo ambiguo", [{"role": "user", "text": "hola"}])

    assert len(seen_modes) == conversation.MAX_TOOL_ROUNDS
    assert seen_modes[:-1] == [None] * (conversation.MAX_TOOL_ROUNDS - 1)
    assert str(seen_modes[-1]).endswith("NONE")
    assert out["reply"] == "En 2025, **50%**."
    assert len(out["tool_calls"]) == conversation.MAX_TOOL_ROUNDS - 1
    assert [r["query"]["group_by"] for r in out["data"]] == ["answer", "sexo"]
    assert [r["result"]["format"] for r in out["data"]] == ["flat", "pivot"]


def test_exec_query_translates_attribute_codes_to_the_requested_wave():
    """El modelo filtra con los códigos del año default, pero cambian entre olas
    (en 2021 y 2022 `sexo` 1 es Hombre). "Mujeres en 2022" tiene que traer a las
    mujeres, no al código 1 crudo de esa ola."""
    from services import wave_service
    from services.catalog_service import get_attributes

    sexo = next(a for a in get_attributes() if a["attribute"] == "sexo")
    mujer = next(v["value"] for v in sexo["values"] if v["label"] == "Mujer")
    checked = 0
    for wave in wave_service.wave_ids():
        if query_tool.resolve_question_for_wave("p111", wave) is None:
            continue
        result, summary, effective = query_tool.execute(
            {
                "question_id": "p111",
                "wave_id": wave,
                "group_by": "sexo",
                "filters": [{"attribute": "sexo", "value": [mujer]}],
            }
        )
        assert result is not None, (wave, summary)
        assert result["counts"]["columns"][2:-1] in (["Mujer"], ["Femenino"]), wave
        # La tarjeta del chat conserva los códigos del catálogo default.
        assert effective["filters"] == [{"attribute": "sexo", "value": [mujer]}]
        checked += 1
    assert checked >= 2


def test_exec_query_untranslatable_filter_is_an_error_not_a_raw_code():
    from services import wave_service

    default = wave_service.default_wave()
    older = [
        w
        for w in wave_service.wave_ids()
        if w != default and query_tool.resolve_question_for_wave("p111", w)
    ]
    if not older:
        pytest.skip("p111 no está en otra ola cargada")
    result, summary, _ = query_tool.execute(
        {
            "question_id": "p111",
            "wave_id": min(older),
            "filters": [{"attribute": "sexo", "value": [424242]}],
        }
    )
    assert result is None
    assert "equivalencia" in summary["error"]
