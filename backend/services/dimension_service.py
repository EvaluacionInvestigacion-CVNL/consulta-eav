"""Dimensiones de filtro: qué se puede filtrar y cómo se traduce entre olas.

Un filtro llega en una de dos formas:

    {"attribute": "sexo", "value": 1}      atributo amigable (o "city_id")
    {"question": "p52", "value": [1, 2]}   cualquier pregunta categórica

Los atributos son preguntas con nombre amigable (`sexo` es `cp2` en 2025 y
`genero` en 2016), así que entre olas las dos formas se traducen igual: se baja
cada código a su opción canónica (`concept_option_id`) y se vuelve a subir en la
pregunta equivalente de la ola destino.

La traducción es ESTRICTA: si un valor no tiene equivalente en alguna ola, la
consulta se rechaza nombrando las olas que faltan. Aplicar el código crudo
—como se hacía antes— filtra la categoría equivocada en silencio.

Todo sale de tres catálogos (~15k filas en total) que se leen una vez y se
cachean: la base es un archivo de sólo lectura, así que traducir un filtro son
búsquedas en diccionarios, no consultas.
"""

from dataclasses import dataclass
from functools import lru_cache

from fastapi import HTTPException

from db_runtime import get_conn
from repositories import responses_repository, survey_repository
from services.catalog_service import get_attributes
from services.ordering import question_sort_key
from services.wave_service import resolve_wave

CITY_ATTRIBUTE = "city_id"


@dataclass(frozen=True)
class _Catalog:
    # (ola, q_id) → (q_type, concept_id, q_text)
    question: dict
    # concept_id → {ola: q_id}
    members_by_concept: dict
    # (ola, q_id, option_id) → concept_option_id
    canonical_by_option: dict
    # (ola, q_id, concept_option_id) → [option_id, …]  (varios códigos de una
    # ola pueden colapsar en la misma opción canónica, p. ej. los "Otro")
    options_by_canonical: dict
    # (ola, atributo) → q_id
    attribute_question: dict


@lru_cache(maxsize=1)
def _catalog() -> _Catalog:
    with get_conn() as conn:
        questions = survey_repository.fetch_all_questions_with_concept(conn)
        options = survey_repository.fetch_all_option_concepts(conn)
        attributes = responses_repository.fetch_attribute_questions(conn)

    question, members_by_concept = {}, {}
    for wave, q_id, q_type, concept_id, q_text in questions:
        question[(wave, q_id)] = (q_type, concept_id, q_text)
        if concept_id:
            members_by_concept.setdefault(concept_id, {})[wave] = q_id

    canonical_by_option, options_by_canonical = {}, {}
    for wave, q_id, option_id, concept_option_id in options:
        canonical_by_option[(wave, q_id, option_id)] = concept_option_id
        options_by_canonical.setdefault((wave, q_id, concept_option_id), []).append(
            option_id
        )

    return _Catalog(
        question=question,
        members_by_concept=members_by_concept,
        canonical_by_option=canonical_by_option,
        options_by_canonical=options_by_canonical,
        attribute_question={
            (wave, attribute): q_id for wave, attribute, q_id in attributes
        },
    )


# ---------------------------------------------------------------------------
# Forma del filtro
# ---------------------------------------------------------------------------


def filter_dimension(filter_spec: dict) -> tuple[str, str]:
    """("attribute" | "question", nombre). Rechaza un filtro malformado."""
    if not isinstance(filter_spec, dict) or "value" not in filter_spec:
        raise HTTPException(status_code=400, detail="Cada filtro necesita `value`.")
    has_attribute = "attribute" in filter_spec
    has_question = "question" in filter_spec
    if has_attribute == has_question:
        raise HTTPException(
            status_code=400,
            detail="Cada filtro lleva `attribute` o `question`, no ambos ni ninguno.",
        )
    kind = "attribute" if has_attribute else "question"
    return kind, filter_spec[kind]


def _as_codes(value) -> list[int]:
    """Los códigos de un filtro como enteros; un valor no numérico es un 400."""
    values = value if isinstance(value, list) else [value]
    try:
        return [int(item) for item in values]
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400, detail=f"Valor de filtro no numérico: {value!r}"
        )


# ---------------------------------------------------------------------------
# Traducción entre olas (vista Año)
# ---------------------------------------------------------------------------


def _translate_codes(catalog, codes, base_wave, base_q, wave, target_q):
    """Los códigos de `base_q` reexpresados en `target_q`, o None si alguno no
    tiene equivalente. Se traduce también en la ola base: la vista Año alinea por
    opción canónica, así que filtrar un "Otro" debe traer todos sus códigos."""
    translated = []
    for code in codes:
        canonical = catalog.canonical_by_option.get((base_wave, base_q, code))
        if canonical is None:
            return None
        in_wave = catalog.options_by_canonical.get((wave, target_q, canonical))
        if not in_wave:
            return None
        translated.extend(in_wave)
    return sorted(set(translated))


def translate_filters_across_waves(
    filters: list[dict],
    base_wave: str,
    member_waves: list[str],
    target_concept_id: str,
) -> dict[str, list[dict]]:
    """Reexpresa los filtros (en la codificación de `base_wave`) en cada ola.

    Devuelve {ola: filtros} listos para `run_query` de esa ola. Si algún filtro
    no puede aplicarse en todas las olas, lanza un 400 con las olas que faltan.
    """
    catalog = _catalog()
    filters_by_wave = {wave: [] for wave in member_waves}
    problems = []

    for filter_spec in filters:
        kind, name = filter_dimension(filter_spec)
        codes = _as_codes(filter_spec["value"])

        if kind == "attribute" and name == CITY_ATTRIBUTE:
            # Los municipios no cambian de código entre olas.
            for wave in member_waves:
                filters_by_wave[wave].append(filter_spec)
            continue

        if kind == "attribute":
            base_q = catalog.attribute_question.get((base_wave, name))
            if base_q is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"El atributo {name!r} no existe en la ola {base_wave}.",
                )
            target_q_by_wave = {
                wave: catalog.attribute_question.get((wave, name))
                for wave in member_waves
            }
            label = name
        else:
            base_question = catalog.question.get((base_wave, name))
            if base_question is None or base_question[0] == "numerica":
                raise HTTPException(
                    status_code=400, detail=f"Unknown filter question: {name}"
                )
            concept_id = base_question[1]
            if not concept_id:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"La pregunta {name} no tiene equivalencia entre años; "
                        "no puede usarse como filtro en la comparación por año."
                    ),
                )
            if concept_id == target_concept_id:
                raise HTTPException(
                    status_code=400,
                    detail="No se puede filtrar una pregunta por sí misma.",
                )
            base_q = name
            target_q_by_wave = {
                wave: catalog.members_by_concept[concept_id].get(wave)
                for wave in member_waves
            }
            label = f"pregunta {name}"

        base_is_numeric = catalog.question[(base_wave, base_q)][0] == "numerica"
        missing_waves = []
        for wave in member_waves:
            target_q = target_q_by_wave[wave]
            if target_q is None:
                missing_waves.append(wave)
                continue
            if base_is_numeric:
                # Una edad es una edad en cualquier ola: el valor viaja tal cual.
                translated = codes
            else:
                translated = _translate_codes(
                    catalog, codes, base_wave, base_q, wave, target_q
                )
                if translated is None and wave == base_wave:
                    # Un código sin opción canónica (p. ej. "No binario" en
                    # 2021) sigue siendo válido en su propia ola; sólo es
                    # intraducible hacia las demás.
                    translated = codes
                if translated is None:
                    missing_waves.append(wave)
                    continue
            filters_by_wave[wave].append(
                {"attribute": name, "value": translated}
                if kind == "attribute"
                else {"question": target_q, "value": translated}
            )

        if missing_waves:
            problems.append(
                f"El filtro {label!r} no tiene equivalencia en "
                f"{', '.join(missing_waves)}."
            )

    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))
    return filters_by_wave


# ---------------------------------------------------------------------------
# Catálogo de dimensiones para la UI
# ---------------------------------------------------------------------------


def _attribute_missing_waves(catalog, attribute, base_wave, member_waves):
    """Olas donde el atributo no existe o no es comparable con el de la base.

    Comparable = la pregunta que lo respalda pertenece al mismo concepto que la
    de la ola base (o, si es numérico como la edad, basta con que exista).
    """
    base_q = catalog.attribute_question[(base_wave, attribute)]
    base_type, base_concept, _ = catalog.question[(base_wave, base_q)]
    missing = []
    for wave in member_waves:
        target_q = catalog.attribute_question.get((wave, attribute))
        if target_q is None:
            missing.append(wave)
            continue
        if base_type == "numerica" or wave == base_wave:
            continue
        target_concept = catalog.question[(wave, target_q)][1]
        if not base_concept or target_concept != base_concept:
            missing.append(wave)
    return missing


@lru_cache(maxsize=256)
def get_dimensions(question_id: str, wave: str | None = None, mode: str = "wave"):
    """Por qué se puede filtrar una pregunta, en una ola o comparando años.

    `mode="wave"`: todos los atributos de la ola y todas sus preguntas
    categóricas (menos la consultada).

    `mode="year"`: sólo lo que existe en TODAS las olas de la pregunta
    consultada. Los atributos se devuelven todos, con `available` y
    `missing_waves`, para que la UI explique por qué uno no aplica; las
    preguntas, sólo las disponibles (listar ~300 inaplicables no le sirve a
    nadie).
    """
    if mode not in ("wave", "year"):
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")
    wave = resolve_wave(wave)
    catalog = _catalog()
    target = catalog.question.get((wave, question_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Question not found")
    _, target_concept, _ = target

    attributes = [
        {"attribute": a["attribute"], "label": a["label"]} for a in get_attributes(wave)
    ]
    candidate_questions = [
        (q_id, concept_id, q_text)
        for (q_wave, q_id), (q_type, concept_id, q_text) in catalog.question.items()
        if q_wave == wave and q_type != "numerica" and q_id != question_id
    ]
    candidate_questions.sort(key=lambda question: question_sort_key(question[0]))

    if mode == "wave":
        return {
            "mode": mode,
            "wave_id": wave,
            "member_waves": [wave],
            "attributes": [
                {**attribute, "available": True, "missing_waves": []}
                for attribute in attributes
            ],
            "questions": [
                {"q_id": q_id, "q_text": q_text, "concept_id": concept_id}
                for q_id, concept_id, q_text in candidate_questions
            ],
        }

    if not target_concept:
        raise HTTPException(
            status_code=400,
            detail="Esta pregunta no tiene equivalencia entre años.",
        )
    member_waves = sorted(catalog.members_by_concept[target_concept])
    for attribute in attributes:
        missing = _attribute_missing_waves(
            catalog, attribute["attribute"], wave, member_waves
        )
        attribute["available"] = not missing
        attribute["missing_waves"] = missing

    covered = set(member_waves)
    return {
        "mode": mode,
        "wave_id": wave,
        "member_waves": member_waves,
        "attributes": attributes,
        "questions": [
            {"q_id": q_id, "q_text": q_text, "concept_id": concept_id}
            for q_id, concept_id, q_text in candidate_questions
            if concept_id
            and concept_id != target_concept
            and covered <= catalog.members_by_concept[concept_id].keys()
        ],
    }
