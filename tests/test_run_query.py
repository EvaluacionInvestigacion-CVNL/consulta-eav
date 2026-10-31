"""Tests for the core query engine (services.query.runner.run_query).

Covers the four shapes (flat/pivot × numeric/categorical) plus the behaviours
that previously broke: numeric frequency breakdown, single 'Promedio' stat row,
city-filter column narrowing, recode grouping, weighting, and sentinel handling.
"""

import pytest

from fastapi import HTTPException

from services.catalog_service import get_questions
from csv_export import _csv_fill_empty
from db_runtime import get_conn
from services.query.models import QueryRequest
from services.query.runner import run_query
from services.wave_service import wave_ids

SENTINELS = {7777, 8888, 9999}


def _pct_sum(rows, col=-1):
    return sum(r[col] for r in rows if isinstance(r[col], (int, float)))


# ── flat (group_by = "answer") ──────────────────────────────────────────────
def test_flat_numeric_is_frequency_breakdown(numeric_qid):
    r = run_query(QueryRequest(question_id=numeric_qid, group_by="answer"))
    assert r["format"] == "flat"
    assert r["column_labels"] == ["Respuesta", "Respuestas", "%"]
    assert len(r["rows"]) >= 1
    # percentages add up to ~100 (allowing per-row rounding)
    tol = max(1.0, 0.06 * len(r["rows"]))
    assert _pct_sum(r["rows"]) == pytest.approx(100, abs=tol)


def test_flat_numeric_excludes_sentinels(numeric_qid):
    r = run_query(QueryRequest(question_id=numeric_qid, group_by="answer"))
    values = {int(row[0]) for row in r["rows"]}
    assert values.isdisjoint(SENTINELS)


def test_flat_categorical_shape(categorical_qid):
    r = run_query(QueryRequest(question_id=categorical_qid, group_by="answer"))
    assert r["format"] == "flat"
    assert r["column_labels"] == ["id_respuesta", "Respuesta", "Total", "%"]
    assert len(r["rows"]) >= 1
    tol = max(1.0, 0.06 * len(r["rows"]))
    assert _pct_sum(r["rows"]) == pytest.approx(100, abs=tol)


# ── Capa A: catálogo incompleto NO debe tirar respuestas (base intacta) ──────
def _flat_base(r):
    return sum(row[2] for row in r["rows"] if isinstance(row[2], (int, float)))


def _raw_weighted_total(wave, qid):
    return get_conn().execute(
        """
        SELECT ROUND(SUM(r.factor_cvnl))::BIGINT
        FROM answers a
        JOIN responses r
          ON r.respondent_id = a.respondent_id AND r.wave_id = a.wave_id
        WHERE a.wave_id = ? AND a.question_id = ? AND a.option_id IS NOT NULL
          AND r.is_initial_respondent = 1
        """,
        [wave, qid],
    ).fetchone()[0] # type: ignore


def test_flat_categorical_base_equals_raw_total(categorical_qid):
    """Regresión Capa A (invariante que sobrevive a Capa B): la base del flat
    categórico = total ponderado crudo de `answers`. El LEFT JOIN no tira nada;
    si volviera a INNER JOIN, las respuestas sin catálogo se caerían, la base se
    encogería y TODOS los % se inflarían (la clase de bug de p128/2021)."""
    r = run_query(QueryRequest(question_id=categorical_qid, initial_only=True))
    base = _flat_base(r)
    assert base > 0
    assert base == pytest.approx(_raw_weighted_total("2025", categorical_qid),
                                 abs=len(r["rows"]))


def test_flat_categorical_uncatalogued_surfaces_as_codigo():
    """Capa A: donde el catálogo aún tiene huecos (olas sin Capa B), el código
    sin etiqueta aflora como 'Código N' y se cuenta — no desaparece. Busca una
    pregunta con hueco dinámicamente; si ya no queda ninguna (Capa B completa en
    todas las olas), se omite."""
    hit = get_conn().execute(
        """
        SELECT a.wave_id, a.question_id
        FROM answers a
        JOIN responses r ON r.wave_id=a.wave_id AND r.respondent_id=a.respondent_id
                        AND r.is_initial_respondent=1
        JOIN questions q ON q.wave_id=a.wave_id AND q.q_id=a.question_id AND q.q_type='categorica'
        LEFT JOIN options o
          ON o.wave_id=a.wave_id AND o.question_id=a.question_id AND o.option_id=a.option_id
        WHERE a.option_id IS NOT NULL AND o.option_id IS NULL
        LIMIT 1
        """
    ).fetchone()
    if not hit:
        pytest.skip("no quedan huecos de catálogo en ninguna ola (Capa B completa)")
    wave, qid = hit
    r = run_query(
        QueryRequest(question_id=qid, group_by="answer", wave_id=wave, initial_only=True)
    )
    assert _flat_base(r) == pytest.approx(_raw_weighted_total(wave, qid), abs=len(r["rows"]))
    assert any(str(row[1]).startswith("Código ") for row in r["rows"])


# ── pivot (group_by != "answer") ────────────────────────────────────────────
def test_pivot_by_attribute(categorical_qid):
    r = run_query(QueryRequest(question_id=categorical_qid, group_by="sexo"))
    assert r["format"] == "pivot"
    cols = r["counts"]["columns"]
    assert cols[0] == "id_respuesta" and cols[-1] == "Total"
    # counts and percentages share the same column layout
    assert r["percentages"]["columns"] == cols
    # there is a Total row in both tables
    assert any(row[0] == "Total" for row in r["counts"]["rows"])
    assert any(row[0] == "Total" for row in r["percentages"]["rows"])


def test_pivot_percentage_total_row_is_100(categorical_qid):
    r = run_query(QueryRequest(question_id=categorical_qid, group_by="sexo"))
    total_row = next(row for row in r["percentages"]["rows"] if row[0] == "Total")
    for cell in total_row[2:]:
        if isinstance(cell, (int, float)):
            assert cell == pytest.approx(100, abs=0.5)


# ── city grouping ───────────────────────────────────────────────────────────
def test_pivot_city_without_filter_has_aggregates(numeric_qid):
    r = run_query(QueryRequest(question_id=numeric_qid, group_by="city_id"))
    group_cols = r["counts"]["columns"][2:-1]
    for agg in ("AMM", "Periferia", "Resto NL", "Nuevo León"):
        assert agg in group_cols
    assert "Monterrey" in group_cols


def test_pivot_city_with_filter_shows_only_filtered(numeric_qid, city_ids):
    r = run_query(
        QueryRequest(
            question_id=numeric_qid,
            filters=[{"attribute": "city_id", "value": list(city_ids.values())}],
            group_by="city_id",
        )
    )
    group_cols = set(r["counts"]["columns"][2:-1])
    assert group_cols == {"Monterrey", "Apodaca"}
    # no aggregate buckets when filtering specific municipalities
    assert group_cols.isdisjoint({"AMM", "Periferia", "Resto NL", "Nuevo León"})


# ── numeric pivot stat rows ─────────────────────────────────────────────────
def test_numeric_pivot_has_only_promedio_stat(numeric_qid):
    r = run_query(QueryRequest(question_id=numeric_qid, group_by="sexo"))
    labels = {row[0] for row in r["counts"]["rows"]}
    assert "Promedio" in labels
    assert labels.isdisjoint({"Mínimo", "Máximo", "Desv. estándar"})


# ── recode grouping ─────────────────────────────────────────────────────────
def test_recode_group_by(numeric_qid):
    r = run_query(
        QueryRequest(question_id=numeric_qid, group_by="tipo_trabajo_remunerado")
    )
    assert r["format"] == "pivot"
    group_cols = r["counts"]["columns"][2:-1]
    assert "Trabajo remunerado" in group_cols


# ── cross-tab: group_by = another survey question ───────────────────────────
def _cross_qids():
    """(A, B): a small categorical question A and a categorical breakdown B,
    both in the default wave, A != B. Prefers a binary Sí/No B for a clean table."""
    qs = get_questions()
    cats = [q for q in qs if q["q_type"] != "numerica" and q["options"]]
    binary = next(
        (q for q in cats if 2 <= len(q["options"]) <= 4 and len(q["options"]) <= 4),
        cats[0],
    )
    a = next(q for q in cats if q["q_id"] != binary["q_id"])
    return a["q_id"], binary["q_id"]


def test_cross_tab_columns_are_breakdown_options():
    """group_by=<q_id> pivots the main question by another question's options:
    columns come from B's catalog (in option_id order), rows from A."""
    a, b = _cross_qids()
    r = run_query(QueryRequest(question_id=a, group_by=b))
    assert r["format"] == "pivot"
    b_labels = {o["label"] for o in next(
        q for q in get_questions() if q["q_id"] == b)["options"]}
    group_cols = set(r["counts"]["columns"][2:-1])
    # every column label is one of B's option labels (Código N fallbacks aside)
    assert group_cols <= b_labels | {c for c in group_cols if c.startswith("Código ")}
    assert group_cols & b_labels  # at least some real B options present


def test_cross_tab_n_matches_table_base():
    """The reported n for a cross-tab is the A∩B base (respondents who answered
    BOTH questions), so the header equals the table's Total row — not the larger
    A-only base, which would overstate n when the breakdown has item non-response."""
    a, b = _cross_qids()
    r = run_query(QueryRequest(question_id=a, group_by=b))
    table_total = next(row for row in r["counts"]["rows"] if row[0] == "Total")[-1]
    assert r["total_respondents"] == table_total


def test_cross_tab_each_column_sums_to_100():
    """Percentages are column-normalised: within each B category the distribution
    of A adds to ~100 (the crosstab reads 'within this B group, how A splits')."""
    a, b = _cross_qids()
    r = run_query(QueryRequest(question_id=a, group_by=b))
    cols = r["percentages"]["columns"]
    data = [row for row in r["percentages"]["rows"] if row[0] != "Total"]
    for ci in range(2, len(cols) - 1):  # skip id/label cols and the Total col
        s = sum(row[ci] for row in data if isinstance(row[ci], (int, float)))
        if s:  # non-empty column
            assert s == pytest.approx(100, abs=max(1.0, 0.06 * len(data)))


def test_cross_tab_numeric_main_has_promedio_row():
    """A numeric main question crossed by a categorical B still gets its weighted
    Promedio row (the group expression is independent of the main q_type)."""
    numeric = next(
        q["q_id"] for q in get_questions() if q["q_type"] == "numerica")
    _, b = _cross_qids()
    r = run_query(QueryRequest(question_id=numeric, group_by=b))
    assert r["format"] == "pivot"
    assert "Promedio" in {row[0] for row in r["counts"]["rows"]}


def test_cross_tab_self_raises_400():
    _, b = _cross_qids()
    with pytest.raises(HTTPException) as exc:
        run_query(QueryRequest(question_id=b, group_by=b))
    assert exc.value.status_code == 400


# ── cruce por una pregunta numérica (rangos) ───────────────────────────────
# `cp4_1` es la edad en 2025: tiene 9999 ("No contesta") además de valores reales.
NUMERIC_QID = "cp4_1"


def _group_columns(result):
    return result["counts"]["columns"][2:-1]


def _total_row(result):
    return next(row for row in result["counts"]["rows"] if row[0] == "Total")


def test_cross_tab_numeric_auto_bins_partition_the_base():
    """Los rangos automáticos parten la base: la suma de las columnas es el
    Total, y los centinelas quedan en su propia columna, no en un rango."""
    a, _ = _cross_qids()
    result = run_query(QueryRequest(question_id=a, group_by=NUMERIC_QID))
    columns = _group_columns(result)
    total_row = _total_row(result)
    assert result["numeric_group_bins"] == sorted(result["numeric_group_bins"])
    assert "No contesta" in columns
    assert not any("9999" in column for column in columns)
    assert sum(total_row[2:-1]) == pytest.approx(total_row[-1], abs=len(columns))


def test_cross_tab_numeric_custom_bins():
    a, _ = _cross_qids()
    result = run_query(
        QueryRequest(question_id=a, group_by=NUMERIC_QID, numeric_group_bins=[30, 45, 60])
    )
    assert result["numeric_group_bins"] == [30, 45, 60]
    ranges = [c for c in _group_columns(result) if not c.startswith("No ")]
    assert ranges == ["Menos de 30", "30-44", "45-59", "60 o más"]


@pytest.mark.parametrize(
    "group_by, numeric_group_bins",
    [
        (NUMERIC_QID, [30, 18]),  # desordenados
        (NUMERIC_QID, []),  # vacíos
        ("sexo", [1, 2]),  # cortes sobre algo que no es numérico
        ("year", [1, 2]),  # la vista Año no tiene rangos
    ],
)
def test_invalid_numeric_group_bins_raise_400(group_by, numeric_group_bins):
    with pytest.raises(HTTPException) as exc:
        run_query(
            QueryRequest(question_id="p114", group_by=group_by, numeric_group_bins=numeric_group_bins)
        )
    assert exc.value.status_code == 400


# ── weighting & filters ─────────────────────────────────────────────────────
def test_weighting_projects_to_population(categorical_qid):
    weighted = run_query(
        QueryRequest(question_id=categorical_qid, initial_only=True)
    )["total_respondents"]
    raw = run_query(
        QueryRequest(question_id=categorical_qid, initial_only=False)
    )["total_respondents"]
    # population projection (factor_cvnl) is far larger than the raw sample
    assert weighted > raw > 0


def test_filter_reduces_total(categorical_qid):
    full = run_query(QueryRequest(question_id=categorical_qid))["total_respondents"]
    filtered = run_query(
        QueryRequest(
            question_id=categorical_qid,
            filters=[{"attribute": "sexo", "value": [1]}],
        )
    )["total_respondents"]
    assert 0 < filtered <= full


# ── filtros por pregunta ────────────────────────────────────────────────────
# `p114` es categórica y existe en todas las olas; `cp2` es la pregunta que respalda
# el atributo `sexo` en 2025, así que filtrar por una u otro debe ser idéntico.
YEAR_QID = "p114"


def _bases(result):
    return [(b["year"], b["base"]) for b in result["year_bases"]]


def test_question_filter_equals_attribute_filter():
    by_attribute = run_query(
        QueryRequest(question_id=YEAR_QID, filters=[{"attribute": "sexo", "value": 1}])
    )
    by_question = run_query(
        QueryRequest(question_id=YEAR_QID, filters=[{"question": "cp2", "value": [1]}])
    )
    assert by_question["total_respondents"] == by_attribute["total_respondents"] > 0
    assert by_question["rows"] == by_attribute["rows"]


def test_question_filter_matches_crosstab_column():
    """Filtrar por P=v da la misma base que la columna v del cross-tab por P."""
    crosstab = run_query(QueryRequest(question_id=YEAR_QID, group_by="cp2"))
    filtered = run_query(
        QueryRequest(question_id=YEAR_QID, filters=[{"question": "cp2", "value": [1]}])
    )
    counts = crosstab["counts"]
    total_row = next(row for row in counts["rows"] if row[0] == "Total")
    mujer = total_row[counts["columns"].index("Mujer")]
    assert sum(row[2] for row in filtered["rows"]) == pytest.approx(mujer, abs=5)


@pytest.mark.parametrize(
    "filter_spec",
    [
        {"question": "p12' OR '1'='1", "value": [1]},  # inyección
        {"question": "cp4_1", "value": [30]},  # numérica (edad)
        {"question": YEAR_QID, "value": [1]},  # la pregunta misma
        {"attribute": "sexo", "question": "cp2", "value": 1},  # ambas llaves
        {"value": 1},  # ninguna
        {"question": "cp2"},  # sin valor
        {"question": "cp4_1", "value": {"min": 30, "max": 18}},  # rango invertido
        {"question": "cp4_1", "value": {}},  # rango sin extremos
        {"question": "cp2", "value": {"min": 1}},  # rango sobre categórica
    ],
)
def test_invalid_question_filter_raises_400(filter_spec):
    with pytest.raises(HTTPException) as exc:
        run_query(QueryRequest(question_id=YEAR_QID, filters=[filter_spec]))
    assert exc.value.status_code == 400


def test_numeric_question_filter_matches_direct_count():
    """El rango es inclusivo y se aplica sobre `answers.value`."""
    result = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            initial_only=False,
            filters=[{"question": "cp4_1", "value": {"min": 18, "max": 29}}],
        )
    )
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(DISTINCT a.respondent_id)
               FROM answers a
               JOIN answers f ON f.respondent_id = a.respondent_id
                AND f.wave_id = '2025' AND f.question_id = 'cp4_1'
                AND f.value BETWEEN 18 AND 29
               WHERE a.wave_id = '2025' AND a.question_id = ?""",
            [YEAR_QID],
        ).fetchone()
        assert row is not None
        expected = row[0]
    assert result["total_respondents"] == expected > 0


def test_numeric_question_filter_with_only_min_excludes_sentinels():
    """Con sólo `min`, un 9999 no puede pasar como "el valor más alto"."""
    only_min = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            filters=[{"question": "cp4_1", "value": {"min": 60}}],
        )
    )
    bounded = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            filters=[{"question": "cp4_1", "value": {"min": 60, "max": 130}}],
        )
    )
    assert only_min["total_respondents"] == bounded["total_respondents"] > 0


def test_numeric_question_filter_matches_crosstab_column():
    """Filtrar por un rango da la misma base que esa columna del cruce."""
    crosstab = run_query(
        QueryRequest(question_id=YEAR_QID, group_by="cp4_1", numeric_group_bins=[18, 30])
    )
    filtered = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            filters=[{"question": "cp4_1", "value": {"min": 18, "max": 29}}],
        )
    )
    column = crosstab["counts"]["columns"].index("18-29")
    assert sum(row[2] for row in filtered["rows"]) == pytest.approx(
        _total_row(crosstab)[column], abs=5
    )


def test_year_numeric_question_filter_applies_in_every_wave():
    result = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            group_by="year",
            filters=[{"question": "cp4_1", "value": {"min": 18, "max": 29}}],
        )
    )
    bases = _bases(result)
    assert len(bases) >= 5
    assert all(base > 0 for _, base in bases)


def test_numeric_attribute_range_equals_question_range():
    """La edad como atributo y como pregunta (`cp4_1`) filtran a la misma gente."""
    by_attribute = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            filters=[{"attribute": "edad_anos", "value": {"min": 18, "max": 29}}],
        )
    )
    by_question = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            filters=[{"question": "cp4_1", "value": {"min": 18, "max": 29}}],
        )
    )
    assert by_attribute["total_respondents"] == by_question["total_respondents"] > 0
    assert by_attribute["rows"] == by_question["rows"]


@pytest.mark.parametrize("attribute", ["sexo", "city_id"])
def test_range_on_categorical_attribute_raises_400(attribute):
    with pytest.raises(HTTPException) as exc:
        run_query(
            QueryRequest(
                question_id=YEAR_QID,
                filters=[{"attribute": attribute, "value": {"min": 1}}],
            )
        )
    assert exc.value.status_code == 400


def test_year_numeric_attribute_range_applies_in_every_wave():
    result = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            group_by="year",
            filters=[{"attribute": "edad_anos", "value": {"min": 18, "max": 29}}],
        )
    )
    bases = _bases(result)
    assert len(bases) >= 5
    assert all(base > 0 for _, base in bases)


def test_attribute_missing_in_wave_raises_400():
    """`modo_transporte` no existe en 2021: antes daba cero filas en silencio."""
    with pytest.raises(HTTPException) as exc:
        run_query(
            QueryRequest(
                question_id="p1",
                wave_id="2021",
                filters=[{"attribute": "modo_transporte", "value": [1]}],
            )
        )
    assert exc.value.status_code == 400


def test_year_filter_without_equivalence_raises_400():
    """Regresión: `modo_transporte` 2025 no tiene opciones canónicas y antes se
    aplicaba el código crudo en las demás olas, filtrando otra categoría."""
    with pytest.raises(HTTPException) as exc:
        run_query(
            QueryRequest(
                question_id=YEAR_QID,
                group_by="year",
                filters=[{"attribute": "modo_transporte", "value": [1]}],
            )
        )
    assert exc.value.status_code == 400
    assert "2024" in exc.value.detail


def test_year_question_filter_equals_attribute_filter():
    by_attribute = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            group_by="year",
            filters=[{"attribute": "sexo", "value": 1}],
        )
    )
    by_question = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            group_by="year",
            filters=[{"question": "cp2", "value": [1]}],
        )
    )
    assert _bases(by_question) == _bases(by_attribute)
    assert len(_bases(by_question)) >= 5


def test_year_question_filter_uses_each_waves_question_id():
    """El filtro llega con el q_id de 2025 y en cada ola debe aplicarse sobre la
    pregunta equivalente, que no siempre se llama igual (`cp2` es `cp2_1` en
    2021 y 2022)."""
    result = run_query(
        QueryRequest(
            question_id=YEAR_QID,
            group_by="year",
            filters=[{"question": "cp2", "value": [1]}],
        )
    )
    assert "question_id = 'cp2_1'" in result["sql"]
    assert "question_id = 'cp2'" in result["sql"]
    assert all(base > 0 for _, base in _bases(result))


def test_single_wave_result_lists_other_years_versions():
    """Sin agrupar por año, el resultado igual trae cómo se preguntó en cada ola,
    para que la UI enlace las otras versiones."""
    result = run_query(QueryRequest(question_id=YEAR_QID))
    versions = {(t["year"], t["q_id"]) for t in result["year_texts"]}
    assert ("2025", YEAR_QID) in versions
    assert len(versions) >= 5


def test_year_question_filter_without_concept_raises_400():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT q_id FROM questions WHERE wave_id = '2025' "
            "AND q_type != 'numerica' AND concept_id IS NULL LIMIT 1"
        ).fetchone()
        assert row is not None
        orphan = row[0]
    with pytest.raises(HTTPException) as exc:
        run_query(
            QueryRequest(
                question_id=YEAR_QID,
                group_by="year",
                filters=[{"question": orphan, "value": [1]}],
            )
        )
    assert exc.value.status_code == 400


# ── year comparison: transparencia del crudo por año ────────────────────────
def test_year_option_map_exposes_raw_per_year():
    """La comparación por año alinea por opción canónica, pero `year_option_map`
    conserva el código y etiqueta CRUDOS de cada ola (transparencia). sexo se
    recodifica entre olas (2022 1/2 vs 2025 0/1) y se relabela
    (Masculino/Hombre), así que debe haber al menos una opción con differs=True
    y con option_id crudo no estable entre años."""
    r = run_query(QueryRequest(question_id="cp2", group_by="year"))
    # La vista Año ya no incluye id_respuesta: columnas = [Respuesta, ...años].
    assert r["counts"]["columns"][0] == "Respuesta"
    years = r["counts"]["columns"][1:]
    yom = r.get("year_option_map")
    assert yom, "comparación categórica por año debe incluir year_option_map"
    # alineado 1:1 y en orden con los renglones de datos; la etiqueta es col 0
    data_rows = [row for row in r["counts"]["rows"] if row[0] != "Total"]
    assert len(yom) == len(data_rows)
    for entry, row in zip(yom, data_rows):
        assert entry["label"] == row[0]
        assert set(entry["years"]) == set(years)
    # sexo cambia código Y etiqueta entre años → la transparencia lo refleja
    assert any(e["differs"] for e in yom)
    hombre = next(e for e in yom if e["label"] == "Hombre")
    raw_ids = {v["option_id"] for v in hombre["years"].values() if v}
    assert len(raw_ids) > 1  # el código crudo NO es estable entre años


def test_year_sql_is_one_query_with_a_block_per_wave():
    """La vista Año es un solo statement (UNION ALL) y el visor lo muestra con
    un encabezado que lo aclara. Debe incluir un bloque por año miembro."""
    r = run_query(QueryRequest(question_id="cp2", group_by="year"))
    sql = r.get("sql")
    assert sql and "es UNA consulta" in sql
    years = r["counts"]["columns"][1:]
    for w in years:
        assert f"'{w}' AS ola" in sql  # el bloque de distribución de cada ola


def test_year_numeric_empty_base_does_not_crash():
    """`2021 cp3_a1` tiene concept_id (c2025_cp4_2) pero ninguna de sus olas
    aporta un respondiente inicial, así que `total_respondents` es None por año.
    La comparación numérica por año no debe reventar sumando None; devuelve una
    tabla vacía coherente con base 0. (Regresión: TypeError int += None en
    year_comparison.)"""
    r = run_query(QueryRequest(question_id="cp3_a1", group_by="year", wave_id="2021"))
    assert r["format"] == "pivot"
    assert r["total_respondents"] == 0
    assert all(b["base"] == 0 for b in r["year_bases"])
    base_row = next(row for row in r["counts"]["rows"] if row[0] == "Base (ponderada)")
    assert all(cell == 0 for cell in base_row[1:])


# ── cruce autoritativo entre olas (db/concepts/concept_equivalences.csv) ────
import csv as _csv
from pathlib import Path as _Path

_EQUIV = _Path(__file__).resolve().parents[1] / "db" / "concepts" / "concept_equivalences.csv"


def _pairs(decision):
    """Pares con ambas olas cargadas."""
    loaded = wave_ids()
    with open(_EQUIV) as f:
        return [(r["wave_a"], r["q_a"], r["wave_b"], r["q_b"])
                for r in _csv.DictReader(f)
                if r["decision"] == decision
                and r["wave_a"] in loaded and r["wave_b"] in loaded]


def _concept_of(wave, qid):
    row = get_conn().execute(
        "SELECT concept_id FROM questions WHERE wave_id=? AND q_id=?", [wave, qid]
    ).fetchone()
    return row[0] if row else None


def test_authoritative_pairs_share_a_concept():
    """Cada par `comparable` de un cruce hecho a mano queda en un MISMO concepto que
    abarca ambas olas → la pregunta se puede comparar por año. Es la garantía de los
    cruces autoritativos sobre el emparejador por texto."""
    pairs = _pairs("comparable")
    assert len(pairs) > 200  # el cruce completo, no un csv truncado
    bad = [(wa, a, wb, b) for wa, a, wb, b in pairs
           if not (_concept_of(wa, a) and _concept_of(wa, a) == _concept_of(wb, b))]
    assert bad == [], f"pares comparables sin concepto compartido: {bad[:10]}"


def test_excluded_pairs_are_not_forced_comparable():
    """Los pares excluidos (rediseños / códigos reasignados) NO deben terminar en el
    mismo concepto: compararlos daría cifras engañosas."""
    shared = [(wa, a, wb, b) for wa, a, wb, b in _pairs("exclude")
              if _concept_of(wa, a) and _concept_of(wa, a) == _concept_of(wb, b)]
    assert shared == [], f"pares excluidos quedaron comparables: {shared}"


def test_year_comparison_recovers_bare_scale_rating():
    """Una calificación 1..10 que 2024 guardó como categórica (valor en option_id) y
    2025 como numérica se compara como concepto NUMÉRICO, con la columna 2024 llena
    (la vista Año alinea por valor). Regresión del cruce autoritativo."""
    r = run_query(QueryRequest(question_id="p62_1", group_by="year"))
    assert r["question"]["q_type"] == "numerica"
    cols = r["counts"]["columns"]
    assert "2024" in cols and "2025" in cols
    base = next(row for row in r["counts"]["rows"] if row[0] == "Base (ponderada)")
    i24 = cols.index("2024")
    assert isinstance(base[i24], (int, float)) and base[i24] > 0  # 2024 no queda vacío


# ── CSV: rellenar celdas sin respondientes con 0 ────────────────────────────
def test_csv_fill_empty_zeroes_data_but_keeps_labels_and_stats():
    """En el CSV, un grupo sin respondientes exporta 0 (no celda vacía). Pero
    las columnas de etiqueta iniciales y la fila de estadístico (Promedio) NO se
    tocan: un 0 ahí sería una etiqueta rota o un promedio inventado."""
    rows = [
        [11.0, "11.0", "", 146, ""],          # data: vacíos → 0
        ["Total", "", 200, 146, ""],           # total: vacíos → 0
        ["Promedio", "", "", 98.85, ""],       # estadístico: vacíos INTACTOS
    ]
    out = _csv_fill_empty(rows, label_cols=2)
    assert out[0] == [11.0, "11.0", 0, 146, 0]
    assert out[1] == ["Total", "", 200, 146, 0]
    assert out[2] == ["Promedio", "", "", 98.85, ""]  # sin cambios


def test_csv_fill_empty_year_view_uses_one_label_col():
    """La vista Año tiene 1 sola columna de etiqueta (Respuesta)."""
    rows = [["Hombre", "", 51.3], ["Promedio (media)", "", ""]]
    out = _csv_fill_empty(rows, label_cols=1)
    assert out[0] == ["Hombre", 0, 51.3]
    assert out[1] == ["Promedio (media)", "", ""]  # estadístico intacto


# ── error handling ──────────────────────────────────────────────────────────
def test_unknown_question_raises_404():
    with pytest.raises(HTTPException) as exc:
        run_query(QueryRequest(question_id="__does_not_exist__"))
    assert exc.value.status_code == 404


# ── SQL-injection guard (allow-list validation) ─────────────────────────────
def test_unknown_group_by_raises_400(categorical_qid):
    with pytest.raises(HTTPException) as exc:
        run_query(QueryRequest(question_id=categorical_qid, group_by="sexo'; DROP--"))
    assert exc.value.status_code == 400


def test_unknown_filter_attribute_raises_400(categorical_qid):
    with pytest.raises(HTTPException) as exc:
        run_query(
            QueryRequest(
                question_id=categorical_qid,
                filters=[{"attribute": "sexo' OR '1'='1", "value": [1]}],
            )
        )
    assert exc.value.status_code == 400
