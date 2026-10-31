"""Catálogo de la encuesta: preguntas, atributos, ciudades, recodes y presets."""

from functools import lru_cache

from db_runtime import get_conn
from metadata import ATTRIBUTE_LABELS, ID_TO_CITY_NAME, PRESETS, RECODES
from repositories import responses_repository, survey_repository
from services.ordering import ordered_question_ids
from services.wave_service import default_wave, numeric_question_ids, resolve_wave


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


def translate_attr_value(conn, attribute: str, value, from_wave: str, to_wave: str):
    """Convierte un option id de un atributo entre olas mediante su id canónico."""
    if from_wave == to_wave:
        return value

    q_from = responses_repository.fetch_attribute_question_id(
        conn, from_wave, attribute
    )
    q_to = responses_repository.fetch_attribute_question_id(conn, to_wave, attribute)
    if not q_from or not q_to:
        return value

    concept_option_id = survey_repository.fetch_concept_option_id(
        conn, from_wave, q_from, value
    )
    if not concept_option_id:
        return value

    translated = survey_repository.fetch_option_id_by_concept(
        conn, to_wave, q_to, concept_option_id
    )
    return translated if translated is not None else value


def get_presets(wave: str | None = None) -> list[dict]:
    """Presets: combinaciones de `group_by` + filtros que la UI aplica de un clic.

    Cada preset es un cuerpo compatible con /api/query (menos `question_id`).

    Los presets están escritos en la codificación de la ola default (p. ej.
    sexo 0=Hombre, 1=Mujer). Como esa codificación cambia entre años, aquí se
    traducen los valores de filtro a la ola pedida (`wave`) vía la opción
    canónica, para que "MUJERES por unidad geográfica" filtre a mujeres en
    CUALQUIER ola y no caiga en la categoría equivocada o en cero filas.
    """
    target = resolve_wave(wave)
    default = default_wave()
    if target == default:
        return PRESETS
    with get_conn() as conn:
        out = []
        for preset in PRESETS:
            new_filters = []
            for item in preset.get("filters") or []:
                attr = item["attribute"]
                value = item["value"]
                if attr == "city_id":
                    new_filters.append(item)
                    continue
                is_list = isinstance(value, list)
                values = value if is_list else [value]
                translated = [
                    translate_attr_value(conn, attr, v, default, target) for v in values
                ]
                new_filters.append(
                    {
                        "attribute": attr,
                        "value": translated if is_list else translated[0],
                    }
                )
            out.append({**preset, "filters": new_filters})
    return out
