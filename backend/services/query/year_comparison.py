"""La vista Año: compara una pregunta a través de las olas donde existe.

Una sola consulta: el SQL de cada ola es el mismo de la forma plana, 
y las olas se juntan con UNION ALL para pagar un solo viaje a DuckDB. 
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

from fastapi import HTTPException

from db_runtime import get_conn
from repositories import concepts_repository, survey_repository
from services.dimension_service import translate_filters_across_waves
from services.query.models import QueryRequest
from services.query.pivot import format_numeric_label
from services.query.sentinels import YEAR_VIEW_SENTINEL_CODES, is_sentinel_label
from services.wave_service import default_wave, question_catalog, wave_ids

log = logging.getLogger("encuesta")


@dataclass
class ConceptComparison:
    """Todo lo que se necesita de la base para comparar un concepto entre olas."""

    concept_id: str
    concept_label: str
    concept_type: str
    question_text: str
    member_waves: list[str]
    question_id_by_wave: dict[str, str]
    wording_by_wave: list[dict]
    canonical_options: tuple
    canonical_option_by_wave_option: MappingProxyType
    filters_by_wave: dict[str, list[dict]]


def compare_across_waves(request: QueryRequest, build_context) -> dict:
    comparison = _load_comparison(request)

    with get_conn() as conn:
        contexts = [
            build_context(
                conn,
                QueryRequest(
                    question_id=comparison.question_id_by_wave[wave],
                    filters=comparison.filters_by_wave[wave],
                    group_by="answer",
                    initial_only=request.initial_only,
                    wave_id=wave,
                ),
            )
            for wave in comparison.member_waves
        ]
        sql = _union_sql(contexts)
        try:
            rows = conn.execute(sql).fetchall()
        except Exception:
            log.exception("vista Año falló: q=%s", request.question_id)
            raise HTTPException(status_code=500, detail="Error interno.")

    result_by_wave = _results_by_wave(contexts, rows)

    response = {
        "format": "pivot",
        "question": {
            "q_id": request.question_id,
            "q_text": comparison.question_text,
            "q_type": comparison.concept_type,
        },
        "filters_applied": request.filters,
        "group_by": "year",
        "concept": {
            "concept_id": comparison.concept_id,
            "label": comparison.concept_label,
        },
        "year_texts": comparison.wording_by_wave,
        "sql": _sql_listing(sql),
        "year_bases": [
            {"year": wave, "base": result_by_wave[wave]["total_respondents"] or 0}
            for wave in comparison.member_waves
        ],
    }

    if comparison.concept_type == "numerica":
        response.update(_numeric_tables(comparison, result_by_wave))
    else:
        response.update(_categorical_tables(comparison, result_by_wave))
    return response


# ---------------------------------------------------------------------------
# Carga: concepto, miembros, catálogo canónico y filtros traducidos
# (la traducción de filtros vive en `services.dimension_service`)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _concept_metadata(concept_id: str):
    with get_conn() as conn:
        concept = concepts_repository.fetch_concept(conn, concept_id)
        if not concept:
            return None
        members = tuple(concepts_repository.fetch_concept_members(conn, concept_id))
        option_map = MappingProxyType(
            {
                (wave, option_id): concept_option_id
                for wave, option_id, concept_option_id in (
                    survey_repository.fetch_concept_option_map(conn, concept_id)
                )
            }
        )
        canonical_options = tuple(
            concepts_repository.fetch_concept_options(conn, concept_id)
        )
    return concept, members, option_map, canonical_options


def _load_comparison(request: QueryRequest) -> ConceptComparison:
    base_wave = request.wave_id or default_wave()
    if base_wave not in wave_ids():
        raise HTTPException(status_code=400, detail=f"Unknown wave_id: {base_wave}")

    question = question_catalog().get((base_wave, request.question_id))
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    _, concept_id, question_text = question
    if not concept_id:
        raise HTTPException(
            status_code=400,
            detail="Esta pregunta no tiene equivalencia entre años.",
        )

    metadata = _concept_metadata(concept_id)
    if not metadata:
        raise HTTPException(
            status_code=400, detail="Concepto no encontrado para esta pregunta."
        )
    (concept_label, concept_type), members, option_map, canonical_options = metadata

    member_waves = [wave for wave, _, _ in members]
    return ConceptComparison(
        concept_id=concept_id,
        concept_label=concept_label,
        concept_type=concept_type,
        question_text=question_text,
        member_waves=member_waves,
        question_id_by_wave={wave: question_id for wave, question_id, _ in members},
        wording_by_wave=[
            {"year": wave, "q_id": question_id, "q_text": q_text or ""}
            for wave, question_id, q_text in members
        ],
        canonical_options=canonical_options,
        canonical_option_by_wave_option=option_map,
        filters_by_wave=translate_filters_across_waves(
            request.filters, base_wave, member_waves, concept_id
        ),
    )


# ---------------------------------------------------------------------------
# Ejecución: todas las olas en un statement
# ---------------------------------------------------------------------------


def _union_sql(contexts: list) -> str:
    """Distribución y base de cada ola, con el mismo SQL de la forma plana.

    Columnas: parte ('dist' | 'base'), ola, option_id, valor, etiqueta, cnt,
    pct. Cada ola usa su propio `q_type`: un concepto numérico puede tener una
    ola que guardó la escala como categórica. El % se calcula dentro de cada
    bloque (la ventana no cruza el UNION), igual que en la forma plana.
    """
    parts = []
    for context in contexts:
        wave = context.wave
        # `clave` es option_id (BIGINT) o valor (DOUBLE): van en columnas
        # separadas para que el UNION no convierta los códigos en flotantes.
        keys = (
            "NULL::BIGINT AS option_id, clave AS valor"
            if context.question_type == "numerica"
            else "clave AS option_id, NULL::DOUBLE AS valor"
        )
        parts.append(f"""
                SELECT 'dist' AS parte, '{wave}' AS ola, {keys}, etiqueta,
                       ROUND(cnt)::BIGINT AS cnt,
                       ROUND(cnt * 100.0 / SUM(cnt) OVER (), 1) AS pct
                FROM ({context.distribution_sql()}
                )""")
        parts.append(f"""
                SELECT 'base', '{wave}', NULL::BIGINT, NULL::DOUBLE, NULL::VARCHAR,
                       ({context.base_sql().strip()}), NULL""")
    return "\nUNION ALL".join(parts)


def _results_by_wave(contexts: list, rows: list) -> dict:
    """Las filas del statement, por ola, en la misma forma que la consulta
    plana: [código, etiqueta, total, %] o [valor, total, %].

    Mismo orden que la forma plana (por código o valor, NULL al final): las
    tablas de abajo usan `setdefault` y dependen del primero que ven.
    """
    result_by_wave = {
        context.wave: {
            "question": {"q_type": context.question_type},
            "rows": [],
            "total_respondents": None,
        }
        for context in contexts
    }
    numeric = {c.wave for c in contexts if c.question_type == "numerica"}
    for parte, wave, option_id, value, label, cnt, pct in rows:
        if parte == "base":
            result_by_wave[wave]["total_respondents"] = cnt
        elif wave in numeric:
            result_by_wave[wave]["rows"].append([value, cnt, pct])
        else:
            result_by_wave[wave]["rows"].append([option_id, label, cnt, pct])
    for result in result_by_wave.values():
        result["rows"].sort(key=lambda row: (row[0] is None, row[0]))
    return result_by_wave


def _sql_listing(sql: str) -> str:
    """El SQL que se le muestra al usuario. Los separadores son comentarios y no
    líneas en blanco porque el visor del front colapsa las vacías."""
    return (
        "-- La comparación por año es UNA consulta: cada ola es un bloque del\n"
        "-- UNION ALL, y los resultados se alinean por concepto en la app.\n--\n"
        + "\n".join(line for line in sql.strip().splitlines() if line.strip())
    )


# ---------------------------------------------------------------------------
# Numérica: alineación por valor + promedio ponderado por año
# ---------------------------------------------------------------------------


def _numeric_tables(comparison: ConceptComparison, result_by_wave: dict) -> dict:
    member_waves = comparison.member_waves
    counts_by_value_and_wave = {}
    label_by_value = {}
    total_by_wave = {wave: 0.0 for wave in member_waves}

    for wave in member_waves:
        wave_result = result_by_wave[wave]
        stored_as_numeric = wave_result["question"]["q_type"] == "numerica"
        for row in wave_result["rows"]:
            value = row[0]
            count = row[1] if stored_as_numeric else row[2]
            if value is None or value in YEAR_VIEW_SENTINEL_CODES or not count:
                continue
            # Ola que guardó la escala como categórica: el centinela viene con su
            # código crudo (888, 8888…) y contaminaría el promedio.
            if not stored_as_numeric and is_sentinel_label(row[1]):
                continue
            counts_by_value_and_wave[(value, wave)] = (
                counts_by_value_and_wave.get((value, wave), 0) + count
            )
            total_by_wave[wave] += count
            if stored_as_numeric:
                label_by_value.setdefault(value, format_numeric_label(value))
            else:
                label_by_value[value] = row[1]  # la etiqueta categórica gana

    values = sorted(
        {value for value, _ in counts_by_value_and_wave}, key=lambda v: float(v)
    )

    counts_rows, percentage_rows = [], []
    for value in values:
        label = label_by_value.get(value, format_numeric_label(value))
        counts_row, percentage_row = [label], [label]
        for wave in member_waves:
            count = counts_by_value_and_wave.get((value, wave), 0)
            counts_row.append(round(count) if count else "")
            percentage_row.append(
                round(count * 100.0 / total_by_wave[wave], 1)
                if total_by_wave[wave]
                else ""
            )
        counts_rows.append(counts_row)
        percentage_rows.append(percentage_row)

    counts_rows.append(
        ["Total"]
        + [round(total_by_wave[wave]) if total_by_wave[wave] else "" for wave in member_waves]
    )
    percentage_rows.append(
        ["Total"] + [100.0 if total_by_wave[wave] else "" for wave in member_waves]
    )

    average_row: list[str | float] = ["Promedio (media)"]
    total_respondents = 0
    for wave in member_waves:
        weighted_sum = weight_total = 0.0
        for value in values:
            count = counts_by_value_and_wave.get((value, wave), 0)
            if count:
                weighted_sum += float(value) * count
                weight_total += count
        average_row.append(round(weighted_sum / weight_total, 2) if weight_total else "")
        # `total_respondents` es None cuando la base de esa ola es vacía (p. ej.
        # pregunta-matriz sin answers, o todos los valores son centinela).
        total_respondents += result_by_wave[wave]["total_respondents"] or 0

    base_row = ["Base (ponderada)"] + [
        result_by_wave[wave]["total_respondents"] or 0 for wave in member_waves
    ]
    counts_rows.extend([average_row, base_row])

    columns = ["Respuesta", *member_waves]
    return {
        "total_respondents": total_respondents,
        "counts": {"columns": columns, "rows": counts_rows},
        "percentages": {"columns": columns, "rows": percentage_rows},
    }


# ---------------------------------------------------------------------------
# Categórica: alineación por opción canónica
# ---------------------------------------------------------------------------


def _categorical_tables(comparison: ConceptComparison, result_by_wave: dict) -> dict:
    member_waves = comparison.member_waves
    label_by_canonical = {
        option_id: label for option_id, label, _ in comparison.canonical_options
    }
    sort_order_by_canonical = {
        option_id: sort_order for option_id, _, sort_order in comparison.canonical_options
    }

    # Qué opciones canónicas llegó a OFRECER cada ola. Es lo que separa "esa ola
    # preguntó y nadie la eligió" (cero legítimo) de "esa ola no tenía esa
    # respuesta" (celda en blanco): el mapa contiene la pareja (ola, código) si y
    # sólo si el catálogo de esa ola la ofrecía.
    offered_by_wave: dict[str, set[str]] = {wave: set() for wave in member_waves}
    for (wave, _option_id), canonical in comparison.canonical_option_by_wave_option.items():
        if wave in offered_by_wave:
            offered_by_wave[wave].add(canonical)

    counts_by_canonical_and_wave = {}
    total_by_wave = {wave: 0 for wave in member_waves}
    # Código y etiqueta REALES que usó cada ola. El renglón muestra la opción
    # canónica (alineada), pero esto conserva cómo se llamó/codificó cada año →
    # transparencia sin romper la comparación.
    original_by_canonical = {}

    for wave in member_waves:
        for row in result_by_wave[wave]["rows"]:
            option_id, label, count = row[0], row[1], row[2]
            canonical = comparison.canonical_option_by_wave_option.get(
                (wave, option_id)
            ) or f"{comparison.concept_id}:{option_id}"
            counts_by_canonical_and_wave[(canonical, wave)] = (
                counts_by_canonical_and_wave.get((canonical, wave), 0) + (count or 0)
            )
            total_by_wave[wave] += count or 0
            label_by_canonical.setdefault(canonical, label)
            original_by_canonical.setdefault(canonical, {}).setdefault(
                wave, {"option_id": option_id, "label": label}
            )

    canonical_ids = sorted(
        {canonical for canonical, _ in counts_by_canonical_and_wave},
        key=lambda canonical: (sort_order_by_canonical.get(canonical, 9999), canonical),
    )

    counts_rows, percentage_rows, year_option_map = [], [], []
    for canonical in canonical_ids:
        display_id = canonical.split(":")[-1]
        label = label_by_canonical.get(canonical, display_id)
        counts_row, percentage_row = [label], [label]
        for wave in member_waves:
            count = counts_by_canonical_and_wave.get((canonical, wave), 0)
            # Sin la opción → blanco en LAS DOS tablas. Antes los conteos dejaban
            # en blanco todo cero y los porcentajes escribían 0.0 en esa misma
            # celda, así que el usuario leía "nadie la eligió" donde la verdad era
            # "esa ola no la ofrecía".
            if not count and canonical not in offered_by_wave[wave]:
                counts_row.append("")
                percentage_row.append("")
                continue
            counts_row.append(count)
            percentage_row.append(
                round(count * 100.0 / total_by_wave[wave], 1)
                if total_by_wave[wave]
                else ""
            )
        counts_rows.append(counts_row)
        percentage_rows.append(percentage_row)

        # Metadata de transparencia, en paralelo a los renglones de datos.
        # `differs` = el código o la etiqueta crudos NO son iguales en todos los
        # años donde la opción aparece (relabel/recode) → la UI lo marca.
        originals = original_by_canonical.get(canonical, {})
        codes_seen = {str(original["option_id"]) for original in originals.values()}
        labels_seen = {
            (original["label"] or "").strip().lower()
            for original in originals.values()
        }
        year_option_map.append(
            {
                "id_respuesta": display_id,
                "label": label,
                "years": {wave: originals.get(wave) for wave in member_waves},
                "differs": len(codes_seen) > 1 or len(labels_seen) > 1,
            }
        )

    counts_rows.append(["Total"] + [total_by_wave[wave] for wave in member_waves])
    percentage_rows.append(
        ["Total"] + [100.0 if total_by_wave[wave] else "" for wave in member_waves]
    )

    columns = ["Respuesta", *member_waves]
    return {
        "total_respondents": sum(total_by_wave.values()),
        "counts": {"columns": columns, "rows": counts_rows},
        "percentages": {"columns": columns, "rows": percentage_rows},
        # Crudo por año y opción (sólo vista "Año"; NO va al CSV).
        "year_option_map": year_option_map,
    }
