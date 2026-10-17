"""Tests de aceptacion contra cifras PUBLICADAS en la revista anual.

Cada fila de `published_figures.csv` es una cifra que ya salio impresa; el test
corre la consulta equivalente y verifica que el % coincida (dentro de una
tolerancia por redondeo). Sirve de red de regresion: si ponderacion, centinelas,
base o armonizacion mueven un numero publicado, el test truena y cita la fuente.

Columnas del CSV (una fila por celda publicada):
  wave_id       ola / anio de la encuesta, p. ej. 2025
  question_id   id de la pregunta EN ESA ola (numeracion propia de cada anio)
  filters       JSON de filtros, p. ej. [] o [{"attribute":"sexo","value":0}]
  group_by      "answer" (distribucion plana) o un atributo/"year" (pivote)
  option_id     la opcion cuyo % verificas (el id_respuesta / valor de la fila)
  group_value   PIVOTE: la columna a leer (p. ej. "Mujer", "2024"). Vacio si plano
  initial_only  TRUE  = ponderado con factor_cvnl, solo respondiente inicial
                FALSE = conteo crudo de todos los miembros del hogar (las cifras
                        que la revista marca "sin factores de expansion")
                (vacio = TRUE, el default canonico)
  expected_pct  el porcentaje publicado en la revista
  tol           diferencia absoluta permitida (redondeo; p. ej. 0.1 o 0.5)
  source        cita: revista + anio + pagina + que celda es

IMPORTANTE: antes de fijar una cifra, reconciliala. Si no empata suele ser
metodologia (ponderacion, base, redondeo, initial_only), no un bug. Solo agrega
filas que ya verificaste que reproducen.

Correr solo esta suite:  pytest -m published
"""

import csv
import json
from pathlib import Path

import pytest

from db_runtime import get_conn
from repositories import survey_repository
from services.query.models import QueryRequest
from services.query.runner import run_query
from services.wave_service import wave_ids

FIXTURES = Path(__file__).parent / "published_figures.csv"


def _load_cases():
    with FIXTURES.open(encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh) if row.get("wave_id", "").strip()]


def _as_bool(s, default=True):
    s = (s or "").strip().lower()
    if s in ("true", "1", "si", "sí", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return default


def _id_match(row_id, target):
    """Compara option_id tolerando numerico (las preguntas numericas devuelven
    el valor como float, p. ej. 1.0, que debe casar con "1" del CSV)."""
    a, b = str(row_id).strip(), str(target).strip()
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except ValueError:
        return False


CASES = _load_cases()
CASE_WAVES = {c["wave_id"] for c in CASES}


@pytest.mark.published
@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[
        f"{c['wave_id']}/{c['question_id']}/{c['group_by'] or 'answer'}"
        f"/{c.get('group_value') or ''}opt{c['option_id']}"
        for c in CASES
    ],
)
def test_published_figure(case):
    loaded = wave_ids()
    if case["wave_id"] not in loaded or (
        case["group_by"] == "year" and case.get("group_value") not in loaded
    ):
        pytest.skip("ola no cargada en esta BD")
    if case["group_by"] == "year" and loaded < CASE_WAVES:
        # Sin las olas apagadas, la pregunta puede quedarse sin pareja entre años.
        with get_conn() as conn:
            if not survey_repository.fetch_question_concept_id(
                conn, case["wave_id"], case["question_id"]
            ):
                pytest.skip("sin concepto entre las olas cargadas")
    r = run_query(
        QueryRequest(
            question_id=case["question_id"],
            filters=json.loads(case["filters"] or "[]"),
            group_by=case["group_by"] or "answer",
            wave_id=case["wave_id"],
            initial_only=_as_bool(case.get("initial_only")),
        )
    )

    target = str(case["option_id"]).strip()
    if r["format"] == "flat":
        got = next(
            (row[-1] for row in r["rows"] if _id_match(row[0], target)), None
        )
    else:
        # Pivote: localizar la columna por su encabezado (group_value) y la fila
        # por option_id; leer esa celda de la tabla de porcentajes.
        gv = str(case.get("group_value") or "").strip()
        assert gv, f"{case['source']}: group_value es obligatorio en modo pivote"
        cols = r["percentages"]["columns"]
        assert gv in cols, f"{case['source']}: columna '{gv}' no existe en {cols}"
        ci = cols.index(gv)
        rows = r["percentages"]["rows"]
        if r.get("group_by") == "year":
            # La vista Año no expone id_respuesta como columna; el código canónico
            # vive en year_option_map, alineado EN ORDEN con las filas de datos.
            yom = r.get("year_option_map") or []
            data_rows = [row for row in rows if row[0] != "Total"]
            idx = next(
                (i for i, e in enumerate(yom) if _id_match(e["id_respuesta"], target)),
                None,
            )
            row = data_rows[idx] if idx is not None and idx < len(data_rows) else None
        else:
            row = next((row for row in rows if _id_match(row[0], target)), None)
        got = row[ci] if row else None

    assert isinstance(got, (int, float)), (
        f"{case['source']}: opcion {target} no encontrada / sin valor en "
        f"{case['question_id']}/{case['wave_id']} ({case['group_by'] or 'answer'})"
    )

    expected = float(case["expected_pct"])
    tol = float(case["tol"])
    assert got == pytest.approx(expected, abs=tol), (
        f"{case['source']}: esperado {expected}+-{tol}, obtenido {got}"
    )
