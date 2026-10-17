"""La BD construida refleja los insumos hechos a mano.

`data/encuesta_multianual.duckdb` es un binario no versionado que se reconstruye a
mano (`db/build_db.py`). Es fácil editar un CSV de insumo y olvidar reconstruir:
la app y los tests siguen leyendo la BD vieja y el desfase no avisa. Peor, hace
que otros tests fallen con mensajes que parecen bugs de datos.

Estos tests comparan el CONTENIDO de la BD contra el de los insumos, no las
fechas de modificación: git no preserva mtimes, así que un `checkout` limpio
las igualaría y el chequeo por fecha sería inestable en CI.

Si alguno falla, casi siempre la respuesta es:

    .venv/bin/python db/build_db.py
"""

import csv
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EQUIV = ROOT / "db" / "concepts" / "concept_equivalences.csv"
RECODES = ROOT / "db" / "concepts" / "concept_recodes_approved.csv"
OVERLAY_TYPES = ROOT / "db" / "overlays" / "question_type_fixes_approved.csv"
OVERLAY_LABELS = ROOT / "db" / "overlays" / "options_fixes_approved.csv"
OVERLAY_QUESTIONS = ROOT / "db" / "overlays" / "question_fixes_approved.csv"

REBUILD = "La BD está desactualizada respecto a sus insumos. Corre: .venv/bin/python db/build_db.py"


def _rows(path):
    with path.open() as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def conn():
    import db_runtime

    c = db_runtime.get_conn()
    yield c
    c.close()


def _declared_partition(existing):
    """Partición esperada: componentes conexas de los pares `comparable` que
    abarcan >=2 olas. Reimplementa el encadenamiento a propósito — si usara la
    función del builder, un bug de esa función sería invisible aquí."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r in _rows(EQUIV):
        if r["decision"] != "comparable":
            continue
        a, b = (r["wave_a"], r["q_a"]), (r["wave_b"], r["q_b"])
        if a not in existing or b not in existing:
            continue  # ola/pregunta aún no cargada: el build también la ignora
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    groups = defaultdict(set)
    for node in list(parent):
        groups[find(node)].add(node)
    return {frozenset(ns) for ns in groups.values() if len({w for w, _ in ns}) >= 2}


def test_concept_membership_matches_equivalences(conn):
    """La agrupación de preguntas en la BD es EXACTAMENTE la que declara
    concept_equivalences.csv. Cubre las dos direcciones: conceptos que el archivo
    declara y la BD no tiene (falta reconstruir tras agregar pares) y conceptos
    que la BD tiene y el archivo ya no declara (falta reconstruir tras marcar
    `exclude`) — este segundo caso es el que se escapa si sólo se revisan los
    pares declarados."""
    existing = {
        (w, q) for w, q in conn.execute("SELECT wave_id, q_id FROM questions").fetchall()
    }
    actual = defaultdict(set)
    for cid, w, q in conn.execute(
        "SELECT concept_id, wave_id, q_id FROM questions WHERE concept_id IS NOT NULL"
    ).fetchall():
        actual[cid].add((w, q))
    actual = {frozenset(ns) for ns in actual.values()}
    expected = _declared_partition(existing)

    faltan = [sorted(g) for g in expected - actual]
    sobran = [sorted(g) for g in actual - expected]
    assert not faltan and not sobran, (
        f"{REBUILD}\n"
        f"  conceptos declarados que la BD no tiene ({len(faltan)}): {faltan[:3]}\n"
        f"  conceptos en la BD que ya no se declaran ({len(sobran)}): {sobran[:3]}"
    )


def test_question_type_overlay_applied(conn):
    """Cada renglón de question_type_fixes_approved.csv está reflejado en `questions`."""
    bad = []
    for r in _rows(OVERLAY_TYPES):
        row = conn.execute(
            "SELECT q_type FROM questions WHERE wave_id = ? AND q_id = ?",
            [r["wave_id"], r["question_id"]],
        ).fetchone()
        if row and row[0] != r["q_type"]:
            bad.append((r["wave_id"], r["question_id"], r["q_type"], row[0]))
    assert not bad, f"{REBUILD}\n  re-tipados sin aplicar (ola, q, esperado, real): {bad[:5]}"


def test_question_overlay_applied(conn):
    """Cada renglón de question_fixes_approved.csv está reflejado en `questions`.

    El overlay repara los `q_id` que el ETL dejó sin renglón: `rename` unifica
    las dos mitades de una pregunta partida, `insert` da de alta la que no tenía
    ninguna e `drop` borra los duplicados. Se comprueba el estado final —el
    nombre viejo no existe en ninguna tabla y el nuevo sí— porque un `q_id` sin
    renglón en `questions` hace que cualquier par de `concept_equivalences` que
    lo nombre se ignore **en silencio**."""
    bad = []
    for r in _rows(OVERLAY_QUESTIONS):
        wave, action, qid, target = (
            r["wave_id"], r["action"], r["question_id"], r["target"],
        )
        if action == "drop":
            n = conn.execute(
                "SELECT COUNT(*) FROM answers WHERE wave_id = ? AND question_id = ?",
                [wave, qid],
            ).fetchone()[0]
            if n:
                bad.append((wave, qid, "drop", f"quedan {n} respuestas"))
            continue

        final = target or qid
        row = conn.execute(
            "SELECT q_type FROM questions WHERE wave_id = ? AND q_id = ?",
            [wave, final],
        ).fetchone()
        if row is None:
            bad.append((wave, final, action, "sin renglón en questions"))
        elif action == "insert" and row[0] != r["q_type"]:
            bad.append((wave, final, action, f"q_type {row[0]} != {r['q_type']}"))

        if action == "rename":
            n = conn.execute(
                "SELECT COUNT(*) FROM answers WHERE wave_id = ? AND question_id = ?",
                [wave, qid],
            ).fetchone()[0]
            if n:
                bad.append((wave, qid, "rename", f"el nombre viejo sigue con {n} respuestas"))

        # Los reactivos numéricos del overlay traían su dato en `option_id`.
        if row and row[0] == "numerica":
            n = conn.execute(
                "SELECT COUNT(*) FROM answers "
                "WHERE wave_id = ? AND question_id = ? AND option_id IS NOT NULL",
                [wave, final],
            ).fetchone()[0]
            if n:
                bad.append((wave, final, action, f"{n} respuestas sin migrar a value"))

    assert not bad, f"{REBUILD}\n  preguntas sin reparar (ola, q, acción, qué): {bad[:5]}"


def test_sin_q_id_huerfanos_en_2024(conn):
    """Ninguna respuesta de 2024 apunta a un `q_id` sin renglón en `questions`.

    El ETL de 2024 dejó 19 así (68,327 respuestas invisibles para la app y para
    la capa de conceptos); `question_fixes_approved.csv` los repara. Si vuelven
    a aparecer, algún par de `concept_equivalences` está siendo ignorado sin
    aviso."""
    huerfanos = conn.execute(
        """
        SELECT a.question_id, COUNT(*) FROM answers a
        LEFT JOIN questions q ON q.wave_id = a.wave_id AND q.q_id = a.question_id
        WHERE a.wave_id = '2024' AND q.q_id IS NULL
        GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()
    assert not huerfanos, f"{REBUILD}\n  q_id huérfanos en 2024: {huerfanos[:5]}"


def test_option_label_overlay_applied(conn):
    """Cada renglón de options_fixes_approved.csv está reflejado en `options`."""
    bad = []
    for r in _rows(OVERLAY_LABELS):
        row = conn.execute(
            "SELECT option_label FROM options "
            "WHERE wave_id = ? AND question_id = ? AND option_id = ?",
            [r["wave_id"], r["question_id"], int(r["option_id"])],
        ).fetchone()
        if row is None or row[0] != r["option_label"]:
            bad.append(
                (r["wave_id"], r["question_id"], r["option_id"],
                 r["option_label"], None if row is None else row[0])
            )
    assert not bad, (
        f"{REBUILD}\n  etiquetas sin aplicar (ola, q, cod, esperada, real): {bad[:5]}"
    )


def test_recodes_applied(conn):
    """Cada renglón de concept_recodes_approved.csv está reflejado en
    `options.concept_option_id` (es lo que alinea códigos recodificados entre olas)."""
    if not RECODES.exists():
        pytest.skip("sin recodes aprobados")
    loaded = {w for (w,) in conn.execute("SELECT wave_id FROM waves").fetchall()}
    bad = []
    for r in _rows(RECODES):
        if r["wave_id"] not in loaded:
            continue  # ola apagada por feature flag: el build la omite
        row = conn.execute(
            "SELECT concept_option_id FROM options "
            "WHERE wave_id = ? AND question_id = ? AND option_id = ?",
            [r["wave_id"], r["q_id"], int(r["option_id"])],
        ).fetchone()
        if row is None or row[0] != r["concept_option_id"]:
            bad.append(
                (r["wave_id"], r["q_id"], r["option_id"],
                 r["concept_option_id"], None if row is None else row[0])
            )
    assert not bad, (
        f"{REBUILD}\n  recodes sin aplicar (ola, q, cod, esperado, real): {bad[:5]}"
    )
