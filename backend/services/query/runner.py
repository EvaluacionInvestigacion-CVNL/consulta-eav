"""`run_query`: valida la petición, ejecuta el SQL y arma la respuesta.

Cuatro formas de salida, seleccionadas por `group_by`:

    group_by="answer"  → plana: un renglón por opción (categórica) o por valor
                         distinto (numérica), con conteo y porcentaje.
    group_by=<otro>    → pivote: dos tablas (conteos y porcentajes) con renglón
                         y columna Total. Las numéricas agregan "Promedio".

La quinta, `group_by="year"`, vive en `year_comparison.py`.

`initial_only` controla a la vez la cohorte y la ponderación:
  - True  → sólo `is_initial_respondent=1`, proyectado a población vía
            `factor_cvnl` (la metodología canónica de CVNL).
  - False → cuenta cada renglón sin ponderar (conteos crudos de la muestra).
"""

import logging
from dataclasses import dataclass, field

from fastapi import HTTPException

from db_runtime import get_conn
from metadata import ATTRIBUTE_TO_ORDER_KEY, DESIRED_ORDERS, RECODES
from repositories import survey_repository
from services.catalog_service import get_attributes
from services.dimension_service import (
    CITY_ATTRIBUTE,
    attribute_question,
    filter_dimension,
    year_comparability,
)
from services.ordering import order_by_desired
from services.query import year_comparison
from services.query.models import QueryRequest
from services.query.numeric_bins import (
    NumericBins,
    numeric_bins,
    validate_edges,
    validate_range,
)
from services.query.pivot import (
    build_counts_and_percentage_rows,
    collapse_cities_into_buckets,
    resolve_city_buckets,
)
from services.query.sentinels import numeric_sentinel_codes
from services.query.sql_builder import (
    answer_scope_sql,
    attribute_join_sql,
    group_expression_sql,
    question_filter_join_sql,
    value_match_clause,
)
from services.wave_service import (
    categorical_question_ids,
    default_wave,
    numeric_question_ids,
    question_catalog,
    wave_ids,
)

log = logging.getLogger("encuesta")

YEAR_GROUP_BY_ALIASES = ("year", "año", "anio")


@dataclass
class QueryContext:
    """Todo lo que las cuatro formas de salida comparten."""

    request: QueryRequest
    wave: str
    question_type: str
    question_text: str
    filter_joins: str
    city_filter: dict | None
    city_filter_sql: str
    sentinel_exclusion_sql: str
    categorical_qids: frozenset = field(default_factory=frozenset)
    numeric_bins: NumericBins | None = None

    @property
    def question_id(self) -> str:
        return self.request.question_id

    @property
    def group_by(self) -> str:
        return self.request.group_by

    @property
    def weighted(self) -> bool:
        return self.request.initial_only

    @property
    def grouped_by_city(self) -> bool:
        return self.group_by == "city_id"

    @property
    def initial_respondent_filter(self) -> str:
        return "AND r.is_initial_respondent = 1" if self.request.initial_only else ""

    @property
    def count_sql(self) -> str:
        """Conteo ponderado (población estimada) o crudo (muestra)."""
        return "SUM(r.factor_cvnl)" if self.weighted else "COUNT(*)"

    @property
    def rounded_count_sql(self) -> str:
        """Igual que `count_sql` pero entero, para celdas de tabla."""
        return f"ROUND({self.count_sql})::BIGINT" if self.weighted else "COUNT(*)"

    @property
    def average_sql(self) -> str:
        """Media ponderada por `factor_cvnl`, o media simple si no se pondera."""
        if self.weighted:
            return (
                "ROUND((SUM(a.value * r.factor_cvnl) / "
                "NULLIF(SUM(r.factor_cvnl), 0))::NUMERIC, 2)"
            )
        return "ROUND(AVG(a.value)::NUMERIC, 2)"

    def scope(self, extra_where: str = "", include_option_labels: bool = False) -> str:
        """El FROM/WHERE de esta consulta, opcionalmente más restringido."""
        return answer_scope_sql(
            self.wave,
            self.question_id,
            self.filter_joins,
            self.initial_respondent_filter,
            self.city_filter_sql,
            extra_where=extra_where,
            include_option_labels=include_option_labels,
        )

    def base_sql(self) -> str:
        """La base: respondientes únicos, ponderados si aplica.

        Única definición: la usan la forma plana y la vista Año.
        """
        scope = self.scope(extra_where=self.sentinel_exclusion_sql)
        if self.weighted:
            # Suma factor_cvnl sobre (respondiente, factor) distintos.
            return f"""
                SELECT ROUND(SUM(factor_cvnl))::BIGINT FROM (
                    SELECT DISTINCT a.respondent_id, r.factor_cvnl
                    {scope}
                )
            """
        return f"SELECT COUNT(DISTINCT a.respondent_id) {scope}"

    def distribution_sql(self) -> str:
        """Un renglón por opción (categórica) o por valor (numérica).

        Columnas: `clave` (option_id o valor), `etiqueta` (NULL en numéricas) y
        `cnt` sin redondear. Única definición: la usan la forma plana y la
        vista Año. Los códigos sin catálogo afloran como "Código N" y en las
        numéricas los centinelas quedan fuera.
        """
        if self.question_type == "numerica":
            return f"""
                SELECT a.value AS clave, NULL::VARCHAR AS etiqueta,
                       {self.count_sql} AS cnt
                {self.scope(extra_where=self.sentinel_exclusion_sql)}
                GROUP BY a.value"""
        return f"""
                SELECT a.option_id AS clave,
                       COALESCE(o.option_label, 'Código ' || a.option_id::TEXT) AS etiqueta,
                       {self.count_sql} AS cnt
                {self.scope(include_option_labels=True)}
                GROUP BY clave, etiqueta"""

    def response_header(self, total_respondents) -> dict:
        """Los campos que toda respuesta lleva, sea plana o pivote."""
        return {
            "question": {
                "q_id": self.question_id,
                "q_text": self.question_text,
                "q_type": self.question_type,
            },
            "wave_id": self.wave,
            "filters_applied": self.request.filters,
            "group_by": self.group_by,
            **(
                {"numeric_group_bins": list(self.numeric_bins.edges)}
                if self.numeric_bins
                else {}
            ),
            "year_texts": year_comparability(self.wave, self.question_id),
            "total_respondents": total_respondents,
        }


# ---------------------------------------------------------------------------
# Validación — todo identificador del usuario pasa por aquí antes del SQL
# ---------------------------------------------------------------------------


def _resolve_wave(request: QueryRequest) -> str:
    """La ola pedida (o la más reciente), validada contra el catálogo."""
    wave = request.wave_id or default_wave()
    if wave not in wave_ids():
        raise HTTPException(status_code=400, detail=f"Unknown wave_id: {wave}")
    return wave


def _require_question(wave: str, question_id: str) -> tuple[str, str]:
    """(q_type, q_text) de la pregunta pedida, o 404."""
    question = question_catalog().get((wave, question_id))
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    q_type, _, q_text = question
    return q_type, q_text


def _validate_filters(
    request: QueryRequest,
    wave: str,
    valid_attributes: set[str],
    categorical_qids: frozenset,
    numeric_qids: frozenset,
) -> None:
    """Rechaza cualquier atributo o pregunta fuera de la allowlist (guard de
    inyección) y los filtros que no tienen sentido en esta ola."""
    for filter_spec in request.filters:
        kind, name = filter_dimension(filter_spec)
        if kind == "attribute":
            if name != CITY_ATTRIBUTE and name not in valid_attributes:
                raise HTTPException(
                    status_code=400, detail=f"Unknown filter attribute: {name}"
                )
            if isinstance(filter_spec["value"], dict):
                # Un rango sólo tiene sentido si el atributo es numérico (edad).
                if attribute_question(wave, name) not in numeric_qids:
                    raise HTTPException(
                        status_code=400,
                        detail="Un rango {min, max} sólo aplica a atributos numéricos.",
                    )
                problem = validate_range(filter_spec["value"])
                if problem:
                    raise HTTPException(status_code=400, detail=problem)
            continue
        if name in numeric_qids:
            problem = validate_range(filter_spec["value"])
            if problem:
                raise HTTPException(status_code=400, detail=problem)
        elif name in categorical_qids:
            if isinstance(filter_spec["value"], dict):
                raise HTTPException(
                    status_code=400,
                    detail="Un rango {min, max} sólo aplica a preguntas numéricas.",
                )
        else:
            raise HTTPException(
                status_code=400, detail=f"Unknown filter question: {name}"
            )
        if name == request.question_id:
            raise HTTPException(
                status_code=400,
                detail="No se puede filtrar una pregunta por sí misma.",
            )


def _validate_group_by(
    request: QueryRequest,
    valid_attributes: set[str],
    categorical_qids: frozenset,
    numeric_qids: frozenset,
) -> None:
    """Rechaza un `group_by` desconocido o degenerado, y cortes sin sentido."""
    allowed = (
        {"answer", "city_id", "edad_anos"}
        | set(RECODES)
        | valid_attributes
        | categorical_qids
        | numeric_qids
    )
    if request.group_by not in allowed:
        raise HTTPException(
            status_code=400, detail=f"Unknown group_by: {request.group_by}"
        )
    # Cruzar una pregunta consigo misma es degenerado (daría una diagonal).
    if request.group_by == request.question_id:
        raise HTTPException(
            status_code=400,
            detail="No se puede cruzar una pregunta consigo misma.",
        )
    if request.numeric_group_bins is not None:
        if request.group_by not in numeric_qids:
            raise HTTPException(
                status_code=400,
                detail="`numeric_group_bins` sólo aplica al cruzar por una pregunta numérica.",
            )
        problem = validate_edges(request.numeric_group_bins)
        if problem:
            raise HTTPException(status_code=400, detail=problem)


def _build_context(conn, request: QueryRequest) -> QueryContext:
    """Valida la petición completa y devuelve el contexto listo para ejecutar."""
    wave = _resolve_wave(request)
    question_type, question_text = _require_question(wave, request.question_id)

    # La allowlist es la de ESTA ola: un atributo que no existe en ella (p. ej.
    # `modo_transporte` en 2016) daría cero filas en vez de un error.
    valid_attributes = {attribute["attribute"] for attribute in get_attributes(wave)}
    categorical_qids = categorical_question_ids(wave)
    numeric_qids = numeric_question_ids(wave)
    _validate_filters(request, wave, valid_attributes, categorical_qids, numeric_qids)
    _validate_group_by(request, valid_attributes, categorical_qids, numeric_qids)

    # Cada filtro de atributo o de pregunta es un JOIN; el de ciudad es un WHERE
    # sobre `responses`, porque `city_id` vive ahí y no en `respondent_attributes`.
    filter_joins = "".join(
        attribute_join_sql(
            f"ra{index}",
            wave,
            filter_spec["attribute"],
            filter_spec["value"],
            excluded_codes=(
                numeric_sentinel_codes(
                    wave,
                    attribute_question(wave, filter_spec["attribute"])
                    or "",
                )
                if isinstance(filter_spec["value"], dict)
                else ()
            ),
        )
        if "attribute" in filter_spec
        else question_filter_join_sql(
            f"qf{index}", wave, filter_spec["question"], filter_spec["value"]
        )
        for index, filter_spec in enumerate(request.filters)
        if filter_spec.get("attribute") != CITY_ATTRIBUTE
    )
    city_filter = next(
        (f for f in request.filters if f.get("attribute") == CITY_ATTRIBUTE), None
    )
    city_filter_sql = (
        "AND " + value_match_clause("r.city_id", city_filter["value"])
        if city_filter
        else ""
    )

    # Centinelas filtrados sólo en numéricas: las categóricas guardan la
    # respuesta en `option_id` y dejan `a.value` NULL, así que aplicar el filtro
    # ahí tiraría todas las filas (NULL NOT IN (...) es NULL/falsy).
    sentinel_exclusion_sql = ""
    if question_type == "numerica":
        codes = ", ".join(
            str(code) for code in numeric_sentinel_codes(wave, request.question_id)
        )
        sentinel_exclusion_sql = f"AND a.value NOT IN ({codes})"

    return QueryContext(
        request=request,
        wave=wave,
        question_type=question_type,
        question_text=question_text,
        filter_joins=filter_joins,
        city_filter=city_filter,
        city_filter_sql=city_filter_sql,
        sentinel_exclusion_sql=sentinel_exclusion_sql,
        categorical_qids=categorical_qids,
        numeric_bins=(
            numeric_bins(wave, request.group_by, request.numeric_group_bins)
            if request.group_by in numeric_qids
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Forma plana (group_by="answer")
# ---------------------------------------------------------------------------


def _count_base_respondents(conn, context: QueryContext) -> int:
    """La base de la consulta: respondientes únicos, ponderados si aplica."""
    return (conn.execute(context.base_sql()).fetchone() or (0,))[0]


def _flat_result(conn, context: QueryContext, total_respondents) -> dict:
    """Un renglón por opción (categórica) o por valor (numérica), con conteo y
    porcentaje. En las numéricas el valor ES la respuesta: no hay etiqueta."""
    if context.question_type == "numerica":
        columns = "b.clave AS valor"
        column_labels = ["Respuesta", "Respuestas", "%"]
    else:
        columns = "b.clave AS id_respuesta, b.etiqueta AS respuesta"
        column_labels = ["id_respuesta", "Respuesta", "Total", "%"]
    sql = f"""
                    WITH base AS ({context.distribution_sql()}
                    ),
                    totals AS (SELECT SUM(cnt) AS total FROM base)
                    SELECT {columns},
                           ROUND(b.cnt)::BIGINT              AS total,
                           ROUND(b.cnt * 100.0 / t.total, 1) AS pct
                    FROM base b CROSS JOIN totals t
                    ORDER BY b.clave ASC
                """
    rows = conn.execute(sql).fetchall()
    return {
        "format": "flat",
        **context.response_header(total_respondents),
        "column_labels": column_labels,
        "rows": [list(row) for row in rows],
        "sql": sql.strip(),
    }


# ---------------------------------------------------------------------------
# Forma pivote (group_by != "answer")
# ---------------------------------------------------------------------------


def _fetch_group_totals(conn, context: QueryContext, group_expression: str) -> dict:
    """Total por columna INCLUYENDO centinelas.

    Son los denominadores del % y el renglón "Total" de la tabla de conteos, así
    que aquí no se excluye nada: el 100% de una columna es toda su gente.
    """
    sql = f"""
            SELECT {group_expression} AS grupo, {context.rounded_count_sql} AS total
            {context.scope()}
            GROUP BY grupo
            HAVING grupo IS NOT NULL
        """
    return {row[0]: row[1] for row in conn.execute(sql).fetchall()}


def _desired_group_order(conn, context: QueryContext) -> list | None:
    """El orden canónico de las columnas, según de qué se esté agrupando."""
    if context.group_by in RECODES:
        return RECODES[context.group_by].get("order")
    if context.numeric_bins:
        return context.numeric_bins.labels
    if context.group_by in context.categorical_qids:
        # Cross-tab por pregunta: ordena por option_id de la pregunta-desglose
        # (mismo criterio que la vista plana), no alfabéticamente. Los
        # centinelas (8888/9999) caen al final solos.
        return survey_repository.fetch_option_labels_in_code_order(
            conn, context.wave, context.group_by
        )
    order_key = ATTRIBUTE_TO_ORDER_KEY.get(context.group_by)
    return DESIRED_ORDERS.get(order_key) if order_key else None


def _numeric_pivot_result(
    conn,
    context: QueryContext,
    group_expression: str,
    totals_by_group: dict,
    grand_total: int,
    group_keys: list,
    city_ids_by_bucket: dict,
    bucket_labels: list,
    label_by_option_id: dict,
    total_respondents,
) -> dict:
    # Distribución por grupo con TODOS los valores no nulos: los centinelas se
    # excluyen del promedio, no de la distribución.
    frequency_sql = f"""
                SELECT a.value AS id_respuesta, {group_expression} AS grupo, {context.rounded_count_sql} AS cnt
                {context.scope(extra_where="AND a.value IS NOT NULL")}
                GROUP BY id_respuesta, grupo
                ORDER BY id_respuesta
            """
    frequency_rows = conn.execute(frequency_sql).fetchall()

    average_scope = context.scope(extra_where=context.sentinel_exclusion_sql)
    average_sql = f"""
                SELECT {group_expression} AS grupo, {context.average_sql} AS promedio
                {average_scope}
                GROUP BY grupo
                HAVING grupo IS NOT NULL
            """
    average_by_group = {
        row[0]: list(row[1:]) for row in conn.execute(average_sql).fetchall()
    }
    overall_average = list(
        conn.execute(f"SELECT {context.average_sql} {average_scope}").fetchone()
        or [None]
    )

    distinct_values = sorted(
        {row[0] for row in frequency_rows}, key=lambda value: (value is None, value)
    )
    counts_by_cell = {(row[0], row[1]): row[2] for row in frequency_rows}
    group_labels = [str(group) for group in group_keys]

    if context.grouped_by_city:
        counts_by_cell, totals_by_group = collapse_cities_into_buckets(
            distinct_values,
            counts_by_cell,
            totals_by_group,
            bucket_labels,
            city_ids_by_bucket,
        )
        grand_total = totals_by_group.get("Nuevo León", grand_total)
        group_keys = list(bucket_labels)
        group_labels = list(group_keys)
        average_by_group = _averages_per_city_bucket(
            conn, context, bucket_labels, city_ids_by_bucket, average_by_group
        )

    def label_for_value(value):
        key = (
            int(value)
            if value is not None and float(value).is_integer()
            else value
        )
        label = label_by_option_id.get(key)
        if label is not None:
            return label
        return str(value) if value is not None else ""

    columns = ["id_respuesta", "Respuesta", *group_labels, "Total"]
    counts_rows, percentage_rows = build_counts_and_percentage_rows(
        distinct_values,
        label_for_value,
        counts_by_cell,
        group_keys,
        totals_by_group,
        grand_total,
        grouped_by_city=context.grouped_by_city,
    )

    # Fila de promedio: sólo en conteos, porque no es un porcentaje.
    average_row = ["Promedio", ""]
    for group in group_keys:
        value = average_by_group.get(group, [None])[0]
        average_row.append(value if value is not None else "")
    average_row.append(overall_average[0] if overall_average[0] is not None else "")
    counts_rows.append(average_row)

    return {
        "format": "pivot",
        **context.response_header(total_respondents),
        "counts": {"columns": columns, "rows": counts_rows},
        "percentages": {"columns": list(columns), "rows": percentage_rows},
        "sql": frequency_sql.strip(),
    }


def _averages_per_city_bucket(
    conn,
    context: QueryContext,
    bucket_labels: list,
    city_ids_by_bucket: dict,
    average_by_city: dict,
) -> dict:
    """Promedio de cada cubeta geográfica.

    Una cubeta de un solo municipio reutiliza el promedio ya calculado; un
    agregado (AMM, Periferia…) se recalcula por SQL, porque un promedio de
    promedios no es el promedio del conjunto.
    """
    average_by_bucket = {}
    for bucket in bucket_labels:
        city_ids = sorted(int(city) for city in city_ids_by_bucket.get(bucket, set()))
        if not city_ids:
            continue
        if len(city_ids) == 1:
            single_city_average = average_by_city.get(str(city_ids[0]))
            if single_city_average:
                average_by_bucket[bucket] = single_city_average
            continue
        in_clause = ",".join(str(city) for city in city_ids)
        bucket_scope = context.scope(
            extra_where=(
                f"{context.sentinel_exclusion_sql} AND r.city_id IN ({in_clause})"
            )
        )
        row = conn.execute(f"SELECT {context.average_sql} {bucket_scope}").fetchone()
        if row and row[0] is not None:
            average_by_bucket[bucket] = list(row)
    return average_by_bucket


def _categorical_pivot_result(
    conn,
    context: QueryContext,
    group_expression: str,
    totals_by_group: dict,
    grand_total: int,
    group_keys: list,
    city_ids_by_bucket: dict,
    bucket_labels: list,
    label_by_option_id: dict,
    total_respondents,
) -> dict:
    frequency_sql = f"""
            SELECT a.option_id AS id_respuesta,
                   o.option_label AS respuesta,
                   {group_expression} AS grupo,
                   {context.rounded_count_sql} AS cnt
            {context.scope(include_option_labels=True)}
            GROUP BY id_respuesta, respuesta, grupo
            ORDER BY id_respuesta
        """
    frequency_rows = conn.execute(frequency_sql).fetchall()

    first_label_by_option = {}
    for row in frequency_rows:
        first_label_by_option.setdefault(row[0], row[1])
    option_ids = sorted(
        first_label_by_option.keys(), key=lambda key: (key is None, key)
    )
    counts_by_cell = {(row[0], row[2]): row[3] for row in frequency_rows}
    group_labels = [str(group) for group in group_keys]

    if context.grouped_by_city:
        counts_by_cell, totals_by_group = collapse_cities_into_buckets(
            option_ids,
            counts_by_cell,
            totals_by_group,
            bucket_labels,
            city_ids_by_bucket,
        )
        grand_total = totals_by_group.get("Nuevo León", grand_total)
        group_keys = list(bucket_labels)
        group_labels = list(group_keys)

    def label_for_option(option_id):
        label = label_by_option_id.get(option_id)
        if label is not None:
            return label
        return f"Código {option_id}" if option_id is not None else ""

    columns = ["id_respuesta", "Respuesta", *group_labels, "Total"]
    counts_rows, percentage_rows = build_counts_and_percentage_rows(
        option_ids,
        label_for_option,
        counts_by_cell,
        group_keys,
        totals_by_group,
        grand_total,
        grouped_by_city=context.grouped_by_city,
    )

    return {
        "format": "pivot",
        **context.response_header(total_respondents),
        "counts": {"columns": columns, "rows": counts_rows},
        "percentages": {"columns": list(columns), "rows": percentage_rows},
        "sql": frequency_sql.strip(),
    }


def _pivot_result(conn, context: QueryContext, total_respondents) -> dict:
    group_expression = group_expression_sql(
        context.group_by, context.wave, context.numeric_bins
    )
    totals_by_group = _fetch_group_totals(conn, context, group_expression)
    grand_total = sum(totals_by_group.values())

    # En un cruce pregunta×pregunta la base real de la tabla es A∩B (quien
    # respondió AMBAS), no quien respondió A.
    if context.group_by in context.categorical_qids or context.numeric_bins:
        total_respondents = grand_total

    if context.grouped_by_city:
        # Los ids crudos se conservan hasta después de consultar; el colapso a
        # cubetas (11 ciudades AMM + 4 agregados) ocurre sobre los resultados.
        city_ids_by_bucket, bucket_labels = resolve_city_buckets(context.city_filter)
        group_keys = list(totals_by_group.keys())
    else:
        city_ids_by_bucket, bucket_labels = {}, []
        group_keys = order_by_desired(
            list(totals_by_group.keys()),
            str,
            _desired_group_order(conn, context),
        )

    label_by_option_id = dict(
        survey_repository.fetch_options(conn, context.wave, context.question_id)
    )

    build = (
        _numeric_pivot_result
        if context.question_type == "numerica"
        else _categorical_pivot_result
    )
    return build(
        conn,
        context,
        group_expression,
        totals_by_group,
        grand_total,
        group_keys,
        city_ids_by_bucket,
        bucket_labels,
        label_by_option_id,
        total_respondents,
    )


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------


def run_query(request: QueryRequest) -> dict:
    """Ejecuta una consulta y devuelve la tabla lista para la UI o el CSV."""
    if request.group_by in YEAR_GROUP_BY_ALIASES:
        if request.numeric_group_bins is not None:
            raise HTTPException(
                status_code=400,
                detail="`numeric_group_bins` sólo aplica al cruzar por una pregunta numérica.",
            )
        return year_comparison.compare_across_waves(request, _build_context)

    conn = get_conn()
    try:
        context = _build_context(conn, request)
        total_respondents = _count_base_respondents(conn, context)
        if context.group_by == "answer":
            return _flat_result(conn, context, total_respondents)
        return _pivot_result(conn, context, total_respondents)
    except HTTPException:
        raise
    except Exception:
        log.exception(
            "run_query falló: q=%s group_by=%s wave=%s",
            request.question_id,
            request.group_by,
            request.wave_id,
        )
        raise HTTPException(status_code=500, detail="Error interno.")
    finally:
        conn.close()
