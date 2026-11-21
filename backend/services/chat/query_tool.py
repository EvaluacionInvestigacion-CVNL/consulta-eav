"""La herramienta `query`: lo único que el modelo puede invocar.

El modelo nunca emite SQL. Declara aquí qué argumentos acepta, y este módulo los
normaliza, los convierte en un `QueryRequest` y ejecuta el MISMO `run_query` que
usa la UI manual.
"""

from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from db_runtime import get_conn
from repositories import survey_repository
from services import dimension_service, wave_service
from services.query.models import QueryRequest
from services.query.runner import run_query


def query_tool_declaration():
    """Declaración de la herramienta `query` en el formato del SDK."""
    from google.genai import types

    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="query",
                description=(
                    "Consulta agregada sobre la encuesta. Devuelve conteos y "
                    "porcentajes (ponderados a población por defecto) de una "
                    "pregunta, opcionalmente filtrada y/o agrupada."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "question_id": types.Schema(
                            type=types.Type.STRING,
                            description="q_id exacto de la pregunta a analizar.",
                        ),
                        "group_by": types.Schema(
                            type=types.Type.STRING,
                            description=(
                                "'answer', 'city_id', 'year' (comparación entre "
                                "años, solo preguntas comparables ⟳), o el nombre "
                                "de un atributo. Por defecto 'answer'."
                            ),
                        ),
                        "wave_id": types.Schema(
                            type=types.Type.STRING,
                            description=(
                                "Año/ola a consultar (p. ej. '2023'). Omitir para "
                                "el año más reciente. No lo uses junto con "
                                "group_by='year'."
                            ),
                        ),
                        "initial_only": types.Schema(
                            type=types.Type.BOOLEAN,
                            description=(
                                "true = proyectar a población (default). "
                                "false = conteos crudos del muestreo."
                            ),
                        ),
                        "filters": types.Schema(
                            type=types.Type.ARRAY,
                            description="Filtros por atributo del respondiente.",
                            items=types.Schema(
                                type=types.Type.OBJECT,
                                properties={
                                    "attribute": types.Schema(
                                        type=types.Type.STRING,
                                        description="Nombre del atributo (o 'city_id').",
                                    ),
                                    "value": types.Schema(
                                        type=types.Type.ARRAY,
                                        description="Uno o más ids numéricos.",
                                        items=types.Schema(type=types.Type.INTEGER),
                                    ),
                                },
                                required=["attribute", "value"],
                            ),
                        ),
                    },
                    required=["question_id"],
                ),
            )
        ]
    )


# ---------------------------------------------------------------------------
# Normalización de los argumentos que manda el modelo
# ---------------------------------------------------------------------------


def _normalize_value(value):
    """Los ids de opción siempre son enteros, aunque lleguen como texto."""
    if isinstance(value, (list, tuple)):
        return [int(item) for item in value]
    return int(value)


def _normalize_city_value(value):
    """city_id filters only accept numeric municipality ids."""
    items = value if isinstance(value, (list, tuple)) else [value]
    city_ids = []
    for item in items:
        try:
            city_ids.append(int(item))
        except (ValueError, TypeError):
            raise ValueError(
                f"'{item}' no es un city_id válido. Las zonas (AMM, Periferia, etc.) "
                "no se filtran: usa group_by='city_id' y lee esa fila/columna."
            )
    return city_ids


def _normalize_filters(raw_filters) -> list[dict]:
    """Descarta filtros incompletos y deja los valores como ids numéricos."""
    filters = []
    for raw_filter in raw_filters or []:
        attribute = raw_filter.get("attribute")
        value = raw_filter.get("value")
        if not attribute or value is None:
            continue
        normalized = (
            _normalize_city_value(value)
            if attribute == "city_id"
            else _normalize_value(value)
        )
        filters.append({"attribute": attribute, "value": normalized})
    return filters


def resolve_question_for_wave(question_id: str, target_wave: str) -> str | None:
    """Traduce un q_id del catálogo (año default) a su equivalente en `target_wave`
    vía concepto."""
    default_wave = wave_service.default_wave()
    if not target_wave or target_wave == default_wave:
        return question_id
    with get_conn() as conn:
        concept_id = survey_repository.fetch_question_concept_id(
            conn, default_wave, question_id
        )
        if not concept_id:
            return None
        return survey_repository.fetch_question_id_for_concept(
            conn, target_wave, concept_id
        )


def translate_filters_to_wave(filters: list[dict], target_wave: str) -> list[dict]:
    """Reexpresa los filtros del modelo en la codificación de `target_wave`.

    El modelo sólo ve el catálogo de atributos del año default, pero los códigos
    cambian entre olas (en 2021 y 2022 `sexo` 1 es Hombre, no Mujer). Se traduce
    por opción canónica, igual que la vista por año; un valor sin equivalente en
    esa ola es un 400 que el modelo recibe como error, nunca el código crudo."""
    default_wave = wave_service.default_wave()
    if not filters or target_wave == default_wave:
        return filters
    translated = dimension_service.translate_filters_across_waves(
        filters, default_wave, [target_wave], target_concept_id=""
    )
    return translated[target_wave]


# ---------------------------------------------------------------------------
# Ejecución y resumen para el modelo
# ---------------------------------------------------------------------------


def _jsonable(value) -> Any:
    """Recursively coerce a value into plain JSON types."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def summarize_result(result: dict) -> dict[str, Any]:
    """Compact view of a query result to feed back to the model (drops SQL)."""
    summary = {
        "question": result.get("question"),
        "group_by": result.get("group_by"),
        "total_respondents": result.get("total_respondents"),
        "format": result.get("format"),
    }
    if result.get("format") == "flat":
        summary["columns"] = result.get("column_labels")
        summary["rows"] = result.get("rows")
    else:
        summary["counts"] = result.get("counts")
        summary["percentages"] = result.get("percentages")
    return _jsonable(summary)


def execute(args: dict) -> tuple[dict | None, dict[str, Any], dict[str, Any]]:
    """Run one `query` tool call. Returns
    (full_result_for_frontend, summary_for_model, effective_query_for_ui).

    `effective_query_for_ui` describe la consulta que REALMENTE se ejecutó
    (q_id ya traducido a la ola pedida + año), para que la tarjeta del chat no
    muestre el q_id del año default cuando en realidad se consultó otro."""
    group_by = args.get("group_by") or "answer"
    wave_id = args.get("wave_id") or None
    question_id = args.get("question_id")
    if question_id is None:
        raise ValueError("Falta el identificador de la pregunta.")
    year_label = (
        "comparación entre años"
        if group_by == "year"
        else (wave_id or wave_service.default_wave())
    )

    def effective_query(resolved_question_id, filters=None):
        return {
            "question_id": resolved_question_id,
            "group_by": group_by,
            "filters": filters if filters is not None else (args.get("filters") or []),
            "año": year_label,
        }

    try:
        filters = _normalize_filters(args.get("filters"))

        # Para un año específico (no la comparación 'year') hay que traducir el q_id
        # a la numeración de esa ola. 'year' usa el q_id default y se alinea solo.
        wave_filters = filters
        if wave_id and group_by != "year":
            resolved = resolve_question_for_wave(question_id, wave_id)
            if resolved is None:
                return (
                    None,
                    {
                        "error": f"La pregunta no existe o no es comparable en {wave_id}."
                    },
                    effective_query(question_id),
                )
            wave_filters = translate_filters_to_wave(filters, wave_id)
            question_id = resolved

        result = run_query(
            QueryRequest(
                question_id=question_id,
                filters=wave_filters,
                group_by=group_by,
                initial_only=args.get("initial_only", True),
                wave_id=wave_id,
            )
        )
    except HTTPException as error:
        return None, {"error": str(error.detail)}, effective_query(question_id)
    except (ValueError, TypeError, KeyError) as error:
        return (
            None,
            {"error": f"Argumentos inválidos: {error}"},
            effective_query(question_id),
        )

    summary = summarize_result(result)
    summary["año"] = year_label
    # El q_id resuelto (traducido a la ola pedida) para la tarjeta del chat. Los
    # filtros van en los códigos del catálogo default, que es con el que el
    # frontend les pone nombre.
    return result, summary, effective_query(question_id, filters)
