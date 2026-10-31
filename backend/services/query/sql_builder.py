"""Fragmentos de SQL que el motor compone en tiempo de ejecución."""

from metadata import RECODES
from services.query.sentinels import numeric_sentinel_codes
from services.wave_service import categorical_question_ids


def value_match_clause(column: str, value) -> str:
    """`col = 3` para un valor suelto, `col IN (1,2)` para una lista.

    Una lista vacía se vuelve `FALSE` (no "sin filtro"): pedir explícitamente
    cero valores debe devolver cero filas.
    """
    if isinstance(value, list):
        if not value:
            return "FALSE"
        return f"{column} IN ({','.join(str(int(item)) for item in value)})"
    return f"{column} = {int(value)}"


def numeric_range_clause(column: str, value_range: dict, excluded_codes) -> str:
    """`col >= a AND col <= b`, sin centinelas.

    Excluirlos no es opcional: con sólo `min` un 9999 ("No contesta") pasaría
    como si fuera el valor más alto.
    """
    parts = []
    if value_range.get("min") is not None:
        parts.append(f"{column} >= {float(value_range['min'])}")
    if value_range.get("max") is not None:
        parts.append(f"{column} <= {float(value_range['max'])}")
    codes = ",".join(str(int(code)) for code in excluded_codes)
    parts.append(f"{column} NOT IN ({codes})")
    return " AND ".join(parts)


def age_bin_case_sql(column: str) -> str:
    """CASE que convierte una edad en años al rango etario que se muestra."""
    return f"""CASE
        WHEN {column} = 9999 THEN 'No contesta'
        WHEN {column} = 8888 THEN 'No sabe'
        WHEN {column} = 7777 THEN 'No aplica'
        WHEN {column} <=  5 THEN '0-5'
        WHEN {column} <= 12 THEN '6-12'
        WHEN {column} <= 17 THEN '13-17'
        WHEN {column} <= 24 THEN '18-24'
        WHEN {column} <= 34 THEN '25-34'
        WHEN {column} <= 44 THEN '35-44'
        WHEN {column} <= 54 THEN '45-54'
        WHEN {column} <= 64 THEN '55-64'
        WHEN {column} <= 74 THEN '65-74'
        ELSE '75 o más'
    END"""


def recode_bucket_case_sql(recode_key: str, value_column: str) -> str:
    """CASE que colapsa los códigos de un atributo en las cubetas del recode.

    Una cubeta con `values=None` es la cubeta "todo lo demás" y se emite al
    final como `WHEN <col> IS NOT NULL`.
    """
    recode = RECODES[recode_key]
    cases = []
    catch_all_label = None
    for label, values in recode["buckets"]:
        safe_label = label.replace("'", "''")
        if values is None:
            catch_all_label = safe_label
            continue
        codes = ",".join(str(int(value)) for value in values)
        cases.append(f"WHEN {value_column} IN ({codes}) THEN '{safe_label}'")
    if catch_all_label is not None:
        cases.append(f"WHEN {value_column} IS NOT NULL THEN '{catch_all_label}'")
    return "CASE\n        " + "\n        ".join(cases) + "\n    END"


def answer_scope_sql(
    wave,
    question_id,
    filter_joins,
    initial_respondent_filter,
    city_filter_sql,
    extra_where="",
    include_option_labels=False,
):
    """El FROM/JOIN/WHERE que define el universo de la consulta.

    Todas las formas de salida parten de aquí, así que la base (el denominador)
    es la misma en cualquiera de ellas. `include_option_labels` agrega el
    LEFT JOIN al catálogo —LEFT y no INNER a propósito: una respuesta cuyo
    `option_id` falta en `options` igual debe contarse, o la base encoge y todos
    los porcentajes se inflan.
    """
    option_join = (
        f"""
        LEFT JOIN options o
            ON o.wave_id = '{wave}'
            AND o.question_id = a.question_id
            AND o.option_id = a.option_id"""
        if include_option_labels
        else ""
    )
    return f"""
        FROM answers a
        INNER JOIN responses r ON r.respondent_id = a.respondent_id AND r.wave_id = '{wave}'{option_join}
        {filter_joins}
        WHERE a.wave_id = '{wave}' AND a.question_id = '{question_id}'
          {extra_where}
          {initial_respondent_filter}
          {city_filter_sql}"""


def attribute_join_sql(
    alias: str, wave: str, attribute: str, value, excluded_codes=()
) -> str:
    """INNER JOIN que restringe a los respondientes con cierto valor de atributo.

    Cada filtro demográfico es un JOIN propio, así que varios filtros se
    intersectan de forma natural. Un `value` dict es un rango `{min, max}` sobre
    un atributo numérico (la edad); `excluded_codes` son sus centinelas.
    """
    match = (
        numeric_range_clause(f"{alias}.value", value, excluded_codes)
        if isinstance(value, dict)
        else value_match_clause(f"{alias}.value", value)
    )
    return f"""
            INNER JOIN respondent_attributes {alias}
                ON {alias}.respondent_id = r.respondent_id
                AND {alias}.wave_id = '{wave}'
                AND {alias}.attribute = '{attribute}'
                AND {match}"""


def question_filter_join_sql(alias: str, wave: str, question_id: str, value) -> str:
    """INNER JOIN que restringe a quienes dieron cierta respuesta a otra pregunta.

    Mismo patrón que `attribute_join_sql`, pero sobre `answers`. Ninguna pregunta
    guarda más de un renglón por respondiente, así que el JOIN no duplica filas.
    Un `value` dict es un rango `{min, max}` sobre una numérica.
    """
    if isinstance(value, dict):
        match = numeric_range_clause(
            f"{alias}.value", value, numeric_sentinel_codes(wave, question_id)
        )
    else:
        match = value_match_clause(f"{alias}.option_id", value)
    return f"""
            INNER JOIN answers {alias}
                ON {alias}.respondent_id = r.respondent_id
                AND {alias}.wave_id = '{wave}'
                AND {alias}.question_id = '{question_id}'
                AND {match}"""


def group_expression_sql(group_by: str, wave: str, numeric_bins=None) -> str:
    """La expresión que produce la ETIQUETA de columna del pivote.

    Seis casos, en orden de prioridad: ciudad (id crudo, se agrupa después en
    Python), edad (rangos), recode (cubetas de `metadata`), pregunta numérica
    (sus rangos, ver `numeric_bins`), pregunta categórica (cross-tab
    pregunta x pregunta) y, por defecto, un atributo demográfico.
    """
    if group_by == "city_id":
        return "r.city_id::TEXT"
    if group_by == "edad_anos":
        return f"""(
                SELECT {age_bin_case_sql('rg.value')}
                FROM respondent_attributes rg
                WHERE rg.respondent_id = r.respondent_id
                  AND rg.wave_id = '{wave}'
                  AND rg.attribute = 'edad_anos'
                LIMIT 1
            )"""
    if group_by in RECODES:
        source_attribute = RECODES[group_by]["source_attribute"]
        return f"""(
                SELECT {recode_bucket_case_sql(group_by, 'rg.value')}
                FROM respondent_attributes rg
                WHERE rg.respondent_id = r.respondent_id
                  AND rg.wave_id = '{wave}'
                  AND rg.attribute = '{source_attribute}'
                LIMIT 1
            )"""
    if numeric_bins is not None:
        return f"""(
                SELECT {numeric_bins.case_sql('ab.value')}
                FROM answers ab
                WHERE ab.wave_id = '{wave}'
                  AND ab.question_id = '{group_by}'
                  AND ab.respondent_id = r.respondent_id
                LIMIT 1
            )"""
    if group_by in categorical_question_ids(wave):
        # Cross-tab pregunta×pregunta: un código sin catálogo aflora como
        # "Código N" en vez de desaparecer de la tabla.
        return f"""(
                SELECT COALESCE(o2.option_label, 'Código ' || ab.option_id::TEXT)
                FROM answers ab
                LEFT JOIN options o2
                  ON o2.wave_id = '{wave}'
                 AND o2.question_id = '{group_by}'
                 AND o2.option_id = ab.option_id
                WHERE ab.wave_id = '{wave}'
                  AND ab.question_id = '{group_by}'
                  AND ab.respondent_id = r.respondent_id
                LIMIT 1
            )"""
    return f"""(
                SELECT COALESCE(o2.option_label, rg.value::TEXT)
                FROM respondent_attributes rg
                LEFT JOIN options o2
                  ON o2.wave_id = '{wave}'
                 AND o2.question_id = rg.question_id
                 AND o2.option_id = rg.value
                WHERE rg.respondent_id = r.respondent_id
                  AND rg.wave_id = '{wave}'
                  AND rg.attribute = '{group_by}'
                LIMIT 1
            )"""
