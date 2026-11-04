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
