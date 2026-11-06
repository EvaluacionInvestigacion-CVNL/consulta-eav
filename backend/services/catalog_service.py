"""Catálogo de la encuesta: preguntas, atributos, ciudades y recodes."""

from functools import lru_cache

from db_runtime import get_conn
from metadata import ATTRIBUTE_LABELS, ID_TO_CITY_NAME, RECODES
from repositories import responses_repository, survey_repository
from services.ordering import ordered_question_ids
from services.wave_service import numeric_question_ids, resolve_wave


@lru_cache(maxsize=16)
def get_questions(wave: str | None = None) -> list[dict]:
    """Preguntas de una ola con tipo, sección y opciones de respuesta.

    Alimenta el selector de preguntas de la UI.
    """
    wave = resolve_wave(wave)
    with get_conn() as conn:
        questions = survey_repository.fetch_questions(conn, wave)
        result = []
        for q_id, q_text, q_section, q_type, q_info, q_block, concept_id in questions:
            options = []
            if q_type != "numerica":
                options = [
                    {"option_id": oid, "label": lbl}
                    for oid, lbl in survey_repository.fetch_options(conn, wave, q_id)
                ]
            result.append(
                {
                    "q_id": q_id,
                    "q_text": q_text,
                    "q_section": q_section,
                    "q_type": q_type,
                    "q_info": q_info,
                    "q_block": q_block,
                    "concept_id": concept_id,
                    "options": options,
                }
            )
    order = ordered_question_ids([r["q_id"] for r in result])
    pos = {q_id: i for i, q_id in enumerate(order)}
    result.sort(key=lambda r: pos[r["q_id"]])
    return result


@lru_cache(maxsize=16)
def get_attributes(wave: str | None = None) -> list[dict]:
    """Atributos demográficos de una ola con sus valores posibles.

    `respondent_attributes.attribute` → `question_id` en `options`;
    `respondent_attributes.value`     → `option_id` en `options`.
    """
    wave = resolve_wave(wave)
    with get_conn() as conn:
        rows = responses_repository.fetch_attribute_values(conn, wave)
        backing = {
            attribute: q_id
            for w, attribute, q_id in responses_repository.fetch_attribute_questions(
                conn
            )
            if w == wave
        }
    numeric_qids = numeric_question_ids(wave)
    attrs: dict = {}
    for attr, val, label in rows:
        attrs.setdefault(attr, []).append({"value": val, "label": label or str(val)})
    return [
        {
            "attribute": k,
            "label": ATTRIBUTE_LABELS.get(k, k),
            "numeric": backing.get(k) in numeric_qids,
            "values": v,
        }
        for k, v in attrs.items()
    ]


@lru_cache(maxsize=16)
def get_cities(wave: str | None = None) -> list[dict]:
    """`city_id`s distintos de una ola. Un id desconocido cae al id crudo."""
    wave = resolve_wave(wave)
    with get_conn() as conn:
        city_ids = responses_repository.fetch_city_ids(conn, wave)
    return [
        {"city_id": city_id, "name": ID_TO_CITY_NAME.get(city_id, str(city_id))}
        for city_id in city_ids
    ]


def get_recodes() -> list[dict]:
    """Recodes: formas de colapsar los valores de un atributo en cubetas con
    nombre (p. ej. tipo_trabajo → Remunerado / No remunerado / Otro). Se pueden
    usar como `group_by` en /api/query.
    """
    return [
        {
            "key": k,
            "label": v["label"],
            "source_attribute": v["source_attribute"],
            "buckets": [
                {"label": label, "values": values} for label, values in v["buckets"]
            ],
            "order": v.get("order"),
        }
        for k, v in RECODES.items()
    ]
