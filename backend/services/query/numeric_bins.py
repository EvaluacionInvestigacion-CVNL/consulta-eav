"""Rangos para cruzar por una pregunta numérica.

Los cortes llegan en `numeric_group_bins` o se calculan aquí:

  - ≤ 11 valores distintos: cada valor es su propia columna.
  - Si no, los quintiles de la pregunta en esa ola, redondeados a números
    legibles (37.4 → 35, 1952 → 2000) y sin repetir.

Los centinelas son columnas propias.
"""

import math
from dataclasses import dataclass
from functools import lru_cache

from db_runtime import get_conn
from services.query.sentinels import numeric_sentinel_codes

MAX_DISTINCT_FOR_EXACT = 11
MAX_BINS = 20

SENTINEL_LABELS = {7777: "No aplica", 8888: "No sabe", 9999: "No contesta"}
OTHER_SENTINEL_LABEL = "No sabe / No contesta"


@dataclass(frozen=True)
class NumericBins:
    edges: tuple[float, ...]
    ranges: tuple[tuple[str, float | None], ...]
    below_label: str | None
    sentinel_codes: tuple[int, ...]

    @property
    def labels(self) -> list[str]:
        """Orden de columnas: rangos y al final los centinelas."""
        sentinel_labels = [SENTINEL_LABELS[c] for c in (7777, 8888, 9999)]
        if any(code not in SENTINEL_LABELS for code in self.sentinel_codes):
            sentinel_labels.append(OTHER_SENTINEL_LABEL)
        below = [self.below_label] if self.below_label else []
        return below + [label for label, _ in self.ranges] + sentinel_labels

    def case_sql(self, column: str) -> str:
        """CASE que convierte un valor en la etiqueta de su rango."""
        cases = [f"WHEN {column} IS NULL THEN NULL"]
        for code in self.sentinel_codes:
            label = SENTINEL_LABELS.get(code, OTHER_SENTINEL_LABEL)
            cases.append(f"WHEN {column} = {code} THEN '{label}'")
        if self.below_label:
            cases.append(f"WHEN {column} < {self.edges[0]} THEN '{self.below_label}'")
        for label, upper in self.ranges:
            condition = "TRUE" if upper is None else f"{column} < {upper}"
            cases.append(f"WHEN {condition} THEN '{label}'")
        return "CASE\n        " + "\n        ".join(cases) + "\n    END"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _nice(value: float) -> float:
    """Redondea a 2 cifras significativas; desde 10, a múltiplos de 5."""
    if value < 10:
        return float(round(value))
    step = max(10 ** (math.floor(math.log10(value)) - 1), 5)
    return float(round(value / step) * step)


@lru_cache(maxsize=512)
def _value_profile(wave: str, question_id: str):
    codes = ", ".join(str(c) for c in numeric_sentinel_codes(wave, question_id))
    scope = f"""
        FROM answers
        WHERE wave_id = '{wave}' AND question_id = '{question_id}'
          AND value IS NOT NULL AND value NOT IN ({codes})"""
    with get_conn() as conn:
        quintiles, all_integers = conn.execute(
            f"""SELECT quantile_cont(value, [0.2, 0.4, 0.6, 0.8]),
                       bool_and(value = floor(value))
                {scope}"""
        ).fetchone() or (None, None)
        distinct = [
            row[0]
            for row in conn.execute(
                f"SELECT DISTINCT value {scope} ORDER BY 1 LIMIT {MAX_DISTINCT_FOR_EXACT + 1}"
            ).fetchall()
        ]
    return tuple(distinct), tuple(quintiles or ()), bool(all_integers)


def numeric_bins(wave: str, question_id: str, edges=None) -> NumericBins:
    """Los rangos de una pregunta numérica: los de `edges` o los automáticos.

    `wave` y `question_id` ya vienen validados contra la allowlist.
    """
    distinct, quintiles, all_integers = _value_profile(wave, question_id)
    sentinel_codes = tuple(numeric_sentinel_codes(wave, question_id))

    if edges is None and len(distinct) <= MAX_DISTINCT_FOR_EXACT:
        # Cada valor es su columna; no hay "Menos de" porque no hay nada abajo.
        values = [float(v) for v in distinct]
        ranges = tuple(
            (_number(value), values[i + 1] if i + 1 < len(values) else None)
            for i, value in enumerate(values)
        )
        return NumericBins(tuple(values), ranges, None, sentinel_codes)

    if edges is None:
        minimum = float(distinct[0]) if distinct else 0.0
        edges = sorted({minimum, *(_nice(q) for q in quintiles if _nice(q) > minimum)})
        below_label = None  # el primer corte es el mínimo real
    else:
        edges = [float(edge) for edge in edges]
        below_label = f"Menos de {_number(edges[0])}"

    ranges = []
    for i, lower in enumerate(edges):
        upper = edges[i + 1] if i + 1 < len(edges) else None
        if upper is None:
            label = f"{_number(lower)} o más"
        elif all_integers and lower.is_integer() and upper.is_integer():
            last = upper - 1
            label = (
                _number(lower)
                if last == lower
                else f"{_number(lower)}-{_number(last)}"
            )
        else:
            label = f"{_number(lower)} a menos de {_number(upper)}"
        ranges.append((label, upper))
    return NumericBins(tuple(edges), tuple(ranges), below_label, sentinel_codes)


def validate_edges(edges) -> str | None:
    """Mensaje de error si `numeric_group_bins` no sirve como lista de cortes."""
    if not isinstance(edges, list) or not 1 <= len(edges) <= MAX_BINS:
        return f"`numeric_group_bins` debe ser una lista de 1 a {MAX_BINS} cortes."
    if any(
        isinstance(edge, bool)
        or not isinstance(edge, (int, float))
        or not math.isfinite(edge)
        for edge in edges
    ):
        return "`numeric_group_bins` sólo admite números."
    if any(b <= a for a, b in zip(edges, edges[1:])):
        return "`numeric_group_bins` debe ir en orden estrictamente creciente."
    return None


def validate_range(value) -> str | None:
    """Mensaje de error si `value` no es un rango `{min, max}` válido."""
    if not isinstance(value, dict) or not value.keys() <= {"min", "max"}:
        return "Una pregunta numérica se filtra con un rango {min, max}."
    bounds = [value.get("min"), value.get("max")]
    present = [bound for bound in bounds if bound is not None]
    if not present:
        return "El rango necesita `min`, `max` o ambos."
    if any(
        isinstance(bound, bool)
        or not isinstance(bound, (int, float))
        or not math.isfinite(bound)
        for bound in present
    ):
        return "Los extremos del rango deben ser números."
    if bounds[0] is not None and bounds[1] is not None and bounds[0] > bounds[1]:
        return "El rango tiene `min` mayor que `max`."
    return None
