#!/usr/bin/env python3
"""
Construye la base de datos multi-año `data/encuesta_multianual.duckdb`.

Cada ola se carga desde su propia fuente en `data/waves/<año>/` y se inserta con
su `wave_id`.

Reconstruye la BD nueva desde cero en cada ejecución.
"""

import csv
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import duckdb
from dotenv import load_dotenv

load_dotenv()

# Feature flags temporales: el registro (y cómo quitar uno) vive en
# backend/config.py::KNOWN_FEATURES; el build no importa el backend.
FEATURES = {f.strip() for f in os.getenv("FEATURES", "").split(",") if f.strip()}


def feature(name: str) -> bool:
    return name in FEATURES


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

WAVES_DIR = ROOT / "data" / "waves"
SRC_2025 = WAVES_DIR / "2025" / "encuesta.duckdb"  # original (intacta)
DST = ROOT / "data" / "encuesta_multianual.duckdb"  # salida (multi-año)
SCHEMA = HERE / "schema.sql"

DATA_TABLES = ["responses", "questions", "options", "respondent_attributes", "answers"]


# ---------------------------------------------------------------------------
# Esquema
# ---------------------------------------------------------------------------
def _run_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Ejecuta el esquema completo."""
    con.execute(SCHEMA.read_text())


# ---------------------------------------------------------------------------
# Ola 2025 — desde la BD original de una sola ola
# ---------------------------------------------------------------------------
def load_wave_2025(con: duckdb.DuckDBPyConnection) -> None:
    wave = "2025"
    print(f"\n▶ Cargando ola '{wave}' desde {SRC_2025.name} ...")
    con.execute("""
        INSERT INTO waves (wave_id, year, label, n_respondents)
        SELECT '2025', 2025, 'Así Vamos 2025', (SELECT COUNT(*) FROM src.responses)
        """)
    con.execute(f"""
        INSERT INTO responses
        SELECT '{wave}', respondent_id, is_initial_respondent, nombre, factor_cvnl, city_id
        FROM src.responses ORDER BY respondent_id
        """)
    con.execute(f"""
        INSERT INTO questions
        SELECT '{wave}', q_id, q_text, q_section, q_type, q_notes, q_info, q_block, NULL
        FROM src.questions ORDER BY q_id
        """)
    con.execute(f"""
        INSERT INTO options
        SELECT '{wave}', question_id, option_id, option_label, NULL
        FROM src.options ORDER BY question_id, option_id
        """)
    con.execute(f"""
        INSERT INTO respondent_attributes
        SELECT '{wave}', respondent_id, question_id, attribute, value
        FROM src.respondent_attributes ORDER BY respondent_id, attribute
        """)
    con.execute(f"""
        INSERT INTO answers
        SELECT '{wave}', respondent_id, question_id, option_id, value
        FROM src.answers
        ORDER BY question_id, option_id NULLS LAST, respondent_id
        """)


# ---------------------------------------------------------------------------
# Olas en formato ancho — desde CSVs producidos por el ETL (data/waves/<año>/)
# ---------------------------------------------------------------------------
def load_wave_csv(
    con: duckdb.DuckDBPyConnection, wave: str, year: int, label: str
) -> None:
    csv_dir = WAVES_DIR / wave
    print(f"\n▶ Cargando ola '{wave}' desde {csv_dir.relative_to(ROOT)}/ ...")

    def csv(name: str) -> str:
        p = csv_dir / f"{name}.csv"
        if not p.exists():
            sys.exit(f"ERROR: falta el CSV de la ola {wave}: {p}")
        return f"read_csv_auto('{p}', header=true)"

    con.execute(f"""
        INSERT INTO waves (wave_id, year, label, n_respondents)
        SELECT '{wave}', {year}, '{label}', (SELECT COUNT(*) FROM {csv('responses')})
        """)
    con.execute(f"""
        INSERT INTO responses
        SELECT '{wave}', respondent_id,
               CASE WHEN is_initial_respondent THEN 1 ELSE 0 END,
               nombre, factor_cvnl, city_id
        FROM {csv('responses')} ORDER BY respondent_id
        """)
    con.execute(f"""
        INSERT INTO questions
        SELECT '{wave}', q_id, q_text, q_section, q_type, q_notes, NULL, NULL, NULL
        FROM {csv('questions')} ORDER BY q_id
        """)
    con.execute(f"""
        INSERT INTO options
        SELECT '{wave}', question_id, option_id, option_label, NULL
        FROM {csv('options')} ORDER BY question_id, option_id
        """)
    con.execute(f"""
        INSERT INTO respondent_attributes
        SELECT '{wave}', respondent_id, question_id, attribute, value
        FROM {csv('respondent_attributes')} ORDER BY respondent_id, attribute
        """)
    con.execute(f"""
        INSERT INTO answers
        SELECT '{wave}', respondent_id, question_id, option_id, value
        FROM {csv('answers')}
        ORDER BY question_id, option_id NULLS LAST, respondent_id
        """)


# ---------------------------------------------------------------------------
# Reparar el catálogo de PREGUNTAS (overlay curado a mano)
# ---------------------------------------------------------------------------
def apply_question_fixes(con: duckdb.DuckDBPyConnection) -> None:
    """Repara `questions` desde db/overlays/question_fixes_approved.csv.

    El ETL de 2024 dejó 19 `q_id` que aparecen en `answers` pero no tienen
    renglón en `questions` (68,327 respuestas inalcanzables). La causa es que la
    columna *Código* del cuestionario viene vacía en esos reactivos: el ETL
    escribió el catálogo bajo un nombre y las respuestas bajo otro, o no escribió
    el renglón en absoluto. Sin renglón en `questions` la pregunta es invisible
    para la app y cualquier par de `concept_equivalences` que la nombre se ignora
    **en silencio**.

    Tres acciones, en este orden:

    ``drop``    borra las respuestas de un `q_id` (duplicados del ETL).
    ``rename``  unifica bajo un solo nombre las dos mitades de una pregunta
                partida entre `questions`/`options` y `answers`. Se aplica a las
                cuatro tablas; como el nombre destino nunca existe en la tabla
                que se renombra, un choque de PK sería un error de declaración y
                revienta el build.
    ``insert``  da de alta la pregunta que no tiene ninguna mitad.

    Al final, toda pregunta del overlay que quede `numerica` y traiga su dato en
    `answers.option_id` se migra a `answers.value` — el espejo de lo que
    `apply_question_type_fixes` hace en la dirección contraria. Las etiquetas de
    opción que falten se agregan aparte, en `options_fixes_approved.csv`."""

    fixes_file = HERE / "overlays" / "question_fixes_approved.csv"
    if not fixes_file.exists():
        print("\n(sin question_fixes_approved.csv — se omite reparación de preguntas)")
        return

    with fixes_file.open(newline="", encoding="utf-8") as fh:
        fixes = [r for r in csv.DictReader(fh) if r.get("wave_id")]

    n_drop = n_ren = n_ins = 0
    for r in fixes:
        wave, action = r["wave_id"], r["action"]
        qid, target = r["question_id"], r["target"]
        if action == "drop":
            con.execute(
                "DELETE FROM answers WHERE wave_id = ? AND question_id = ?", [wave, qid]
            )
            con.execute(
                "DELETE FROM options WHERE wave_id = ? AND question_id = ?", [wave, qid]
            )
            con.execute(
                "DELETE FROM questions WHERE wave_id = ? AND q_id = ?", [wave, qid]
            )
            n_drop += 1
        elif action == "rename":
            con.execute(
                "UPDATE questions SET q_id = ? WHERE wave_id = ? AND q_id = ?",
                [target, wave, qid],
            )
            for table in ("options", "answers", "respondent_attributes"):
                con.execute(
                    f"UPDATE {table} SET question_id = ? "
                    "WHERE wave_id = ? AND question_id = ?",
                    [target, wave, qid],
                )
            n_ren += 1
        elif action == "insert":
            con.execute(
                "INSERT INTO questions (wave_id, q_id, q_text, q_section, q_type) "
                "VALUES (?, ?, ?, ?, ?)",
                [wave, qid, r["q_text"], r["q_section"], r["q_type"]],
            )
            n_ins += 1
        else:
            sys.exit(f"ERROR: acción desconocida en {fixes_file.name}: {action!r}")

    # Los reactivos numéricos traen sus minutos/horas en `option_id` porque el
    # ETL no sabía su tipo. Ahí no sirven: los agregados numéricos leen `value`.
    finales = {(r["wave_id"], r["target"] or r["question_id"]) for r in fixes}
    n_mig = 0
    for wave, qid in sorted(finales):
        moved = con.execute(
            """
            UPDATE answers a SET value = CAST(a.option_id AS DOUBLE), option_id = NULL
            FROM questions q
            WHERE q.wave_id = a.wave_id AND q.q_id = a.question_id
              AND a.wave_id = ? AND a.question_id = ?
              AND q.q_type = 'numerica'
              AND a.value IS NULL AND a.option_id IS NOT NULL
            """,
            [wave, qid],
        ).fetchone()[0]  # type: ignore
        n_mig += moved or 0

    huerfanos = con.execute(
        """
        SELECT COUNT(*) FROM answers a
        LEFT JOIN questions q ON q.wave_id = a.wave_id AND q.q_id = a.question_id
        WHERE q.q_id IS NULL
        """
    ).fetchone()[0]  # type: ignore
    print(
        f"\n▶ Preguntas reparadas desde {fixes_file.name}: {n_ren} renombradas,"
        f" {n_ins} dadas de alta, {n_drop} borradas"
        f" ({n_mig:,} respuestas numéricas migradas option_id→value)"
    )
    print(f"  Respuestas sin renglón en questions: {huerfanos:,}")


# ---------------------------------------------------------------------------
# Aplicar reparación del catálogo de opciones (overlay curado a mano)
# ---------------------------------------------------------------------------
def apply_option_fixes(con: duckdb.DuckDBPyConnection) -> None:
    """Upsert de db/overlays/options_fixes_approved.csv sobre `options`.

    Las fuentes a veces no traen etiqueta para códigos que sí aparecen en `answers`. 
    Este overlay agrega/corrige esas etiquetas SIN tocar las fuentes crudas. 
    Regla: si (wave, q, option) existe, se reemplaza la etiqueta; si no, se inserta."""

    fixes_file = HERE / "overlays" / "options_fixes_approved.csv"
    if not fixes_file.exists():
        print("\n(sin options_fixes_approved.csv — se omite reparación de etiquetas)")
        return
    con.execute(f"""
        CREATE TEMP TABLE _ofix AS
        SELECT CAST(wave_id AS VARCHAR)     AS wave_id,
               CAST(question_id AS VARCHAR) AS question_id,
               CAST(option_id AS BIGINT)    AS option_id,
               CAST(option_label AS VARCHAR) AS option_label
        FROM read_csv_auto('{fixes_file}', header=true)
        """)
    con.execute("""
        DELETE FROM options o
        USING _ofix f
        WHERE o.wave_id = f.wave_id
          AND o.question_id = f.question_id
          AND o.option_id = f.option_id
        """)
    con.execute("""
        INSERT INTO options (wave_id, question_id, option_id, option_label, concept_option_id)
        SELECT wave_id, question_id, option_id, option_label, NULL FROM _ofix
        """)
    n = con.execute("SELECT COUNT(*) FROM _ofix").fetchone()[0]  # type: ignore
    con.execute("DROP TABLE _ofix")
    print(f"\n▶ {n} etiquetas de opción reparadas desde {fixes_file.name}")


def apply_question_type_fixes(con: duckdb.DuckDBPyConnection) -> None:
    """Re-tipa preguntas desde db/overlays/question_type_fixes_approved.csv.

    Algunas preguntas vienen catalogadas como `numerica` en la fuente pero son
    en realidad IDENTIFICADORES (colonia de destino, ruta de camión).
    
    Este overlay corrige `q_type` SIN tocar las fuentes crudas.

    Aquí también se migra el código `value → option_id` para esas preguntas."""

    fixes_file = HERE / "overlays" / "question_type_fixes_approved.csv"
    if not fixes_file.exists():
        print("\n(sin question_type_fixes_approved.csv — se omite re-tipado)")
        return
    con.execute(f"""
        CREATE TEMP TABLE _tfix AS
        SELECT CAST(wave_id AS VARCHAR)     AS wave_id,
               CAST(question_id AS VARCHAR) AS question_id,
               CAST(q_type AS VARCHAR)      AS q_type
        FROM read_csv_auto('{fixes_file}', header=true)
        """)
    con.execute("""
        UPDATE questions q
        SET q_type = f.q_type
        FROM _tfix f
        WHERE q.wave_id = f.wave_id AND q.q_id = f.question_id
        """)
    n = con.execute("""
        SELECT COUNT(*) FROM _tfix f
        JOIN questions q ON q.wave_id = f.wave_id AND q.q_id = f.question_id
                        AND q.q_type = f.q_type
        """).fetchone()[0]  # type: ignore
    
    # Migrar el código de `value` a `option_id` sólo para las re-tipadas a
    # categórica.
    con.execute("""
        UPDATE answers a
        SET option_id = CAST(a.value AS BIGINT), value = NULL
        FROM _tfix f
        WHERE a.wave_id = f.wave_id AND a.question_id = f.question_id
          AND f.q_type = 'categorica'
          AND a.option_id IS NULL AND a.value IS NOT NULL
        """)
    con.execute("DROP TABLE _tfix")
    print(
        f"\n▶ Re-tipado: {n} preguntas identificador → categórica desde {fixes_file.name}"
        f" (código value→option_id migrado)"
    )


# ---------------------------------------------------------------------------
# Armonización entre años
# ---------------------------------------------------------------------------
# Un CONCEPTO agrupa la misma pregunta a través los años años, de modo que 
# `group_by="year"` pueda compararla en el tiempo.
#
# Todo el insumo es HECHO A MANO y vive en dos CSV:
#
#   concept_equivalences.csv
#       Un renglón por PAR de preguntas equivalentes entre dos olas. Los pares se
#       encadenan de forma transitiva.
#
#   concept_recodes_approved.csv
#       Sólo para opciones RECODIFICADAS entre olas.

SENT_CODES = {7777, 8888, 9999}  # No aplica / No sabe / No contesta
SENT_LABEL_RE = re.compile(r"no\s*(sabe|contest|aplica|respond)", re.I)
# La ola 2021 etiqueta sus centinelas con SIGLAS: NS en el código 8 (144
# preguntas), NC en el 9 (141) y NA en el 99 (3), más 'NS/NC' en 11 preguntas.
# Ninguna otra ola las usa. Sin esto entraban al catálogo canónico como
# categorías sustantivas y COLISIONABAN con la opción que usa ese mismo código
# en la otra ola (p. ej. 2021 p33 código 8 = 'NS' contra 2022 p39 código 8 =
# 'Otro'). Se ancla a la etiqueta COMPLETA para no capturar palabras que
# casualmente contengan esas letras.
SENT_ABBR_RE = re.compile(r"^\s*(NS\s*/\s*NC|NS|NC|NA)\s*$", re.I)
SENT_ABBR_KIND = {"NS": "ns", "NC": "nc", "NA": "na", "NS/NC": "ns"}
SENT_CANON = {
    "ns": (8888, "No sabe"),
    "nc": (9999, "No contesta"),
    "na": (7777, "No aplica"),
}


def _is_sentinel(option_id: int, label: str) -> bool:
    """Centinela por CÓDIGO estándar, por ETIQUETA o por SIGLA."""
    text = str(label or "")
    return (
        option_id in SENT_CODES
        or bool(SENT_LABEL_RE.search(text))
        or bool(SENT_ABBR_RE.match(text))
    )


def _sentinel_kind(label: str) -> str:
    text = str(label or "")
    # La sigla se resuelve PRIMERO: decidir por subcadena mandaría 'NS' al
    # caso por defecto ('nc') porque no contiene 'sabe' ni 'aplica'.
    m = SENT_ABBR_RE.match(text)
    if m:
        return SENT_ABBR_KIND[re.sub(r"\s+", "", m.group(1)).upper()]
    low = text.lower()
    return "ns" if "sabe" in low else "na" if "aplica" in low else "nc"


def load_concepts(con: duckdb.DuckDBPyConnection) -> None:
    concepts_dir = HERE / "concepts"
    equivalences_dir = concepts_dir / "concept_equivalences.csv"
    recodes_dir = concepts_dir / "concept_recodes_approved.csv"

    if not equivalences_dir.exists():
        print(
            f"\n⚠️  SIN CONCEPTOS: falta {equivalences_dir.relative_to(ROOT)}."
            "\n    La BD se construirá SIN comparación por año.\n"
        )
        return
    print(f"\n▶ Construyendo conceptos desde {equivalences_dir.relative_to(ROOT)} ...")

    # --- hechos de la BD ya cargada -----------------------------------------
    qtype, qtext = {}, {}
    for wave, qid, _qtype, _qtext in con.execute(
        "SELECT wave_id,q_id,q_type,q_text FROM questions"
    ).fetchall():
        qtype[(wave, qid)] = _qtype or ""
        qtext[(wave, qid)] = _qtext or ""

    opts: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
    for wave, qid, oid, olabel in con.execute(
        "SELECT wave_id,question_id,option_id,option_label FROM options"
    ).fetchall():
        opts[(wave, qid)][oid] = olabel or ""

    # --- encadenar los pares comparables (union-find) ------------------------
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    rows = list(csv.DictReader(equivalences_dir.open()))
    pinned, declared_type, skipped = {}, {}, 0
    excluded_pairs = []
    warnings: list[str] = []
    for r in rows:
        a, b = (r["wave_a"], r["q_a"]), (r["wave_b"], r["q_b"])
        if a not in qtype or b not in qtype:
            skipped += 1  # ola/pregunta aún no cargada: se ignora
            continue
        if r["decision"] == "exclude":
            excluded_pairs.append((a, b, r.get("note", "")))
            continue
        # aviso: par declarado comparable cuyas opciones NO alinean por código
        if r["ctype"] == "categorica":
            ca, cb = (
                {o for o, l in opts.get(n, {}).items() if not _is_sentinel(o, l)}
                for n in (a, b)
            )
            if ca and cb and ca != cb:
                # mostrar SÓLO la diferencia: la lista completa de códigos suele
                # ser idéntica en los primeros elementos y esconde el desajuste.
                only_a, only_b = sorted(ca - cb), sorted(cb - ca)
                warnings.append(
                    f"códigos divergentes {a[0]}/{a[1]} ↔ {b[0]}/{b[1]}: "
                    f"sólo en {a[0]}={only_a or '—'}, sólo en {b[0]}={only_b or '—'}"
                )
        union(a, b)
        if r.get("concept_id"):
            pinned[find(a)] = r["concept_id"]
        declared_type[find(a)] = r["ctype"]

    groups: dict[tuple[str, str], set] = defaultdict(set)
    for node in list(parent):
        groups[find(node)].add(node)

    # --- id, tipo y etiqueta por concepto ------------------------------------
    concepts: dict[str, dict] = {}
    members: dict[str, set] = {}
    for root, nodes in groups.items():
        if len({w for w, _ in nodes}) < 2:
            continue  # una sola ola: no hay nada que comparar
        roots = {find(n) for n in nodes} | {root}
        cid = next((pinned[r] for r in roots if r in pinned), None)
        newest = max(nodes)
        if cid is None:
            cid = f"c{newest[0]}_{newest[1]}"
        ctype = next(
            (declared_type[r] for r in roots if r in declared_type), "categorica"
        )
        # Etiqueta = texto de la pregunta en la ola más reciente. El q_text crudo
        # trae saltos de línea ("Nota para el encuestador(a): …"), y la etiqueta se
        # muestra en la vista Año → se colapsa el espacio en blanco.
        label = " ".join((qtext.get(newest) or cid).split())
        concepts[cid] = {
            "concept_id": cid,
            "label": label[:80],
            "q_type": ctype,
        }
        members[cid] = nodes

    # --- recodes aprobados ----------------------------------------------------
    recodes: dict[tuple[str, str, str], list[tuple[int, str]]] = defaultdict(list)
    skipped_recodes = 0
    if recodes_dir.exists():
        for r in csv.DictReader(recodes_dir.open()):
            if (r["wave_id"], r["q_id"]) not in qtype:
                skipped_recodes += 1  # ola/pregunta aún no cargada, como los pares
                continue
            recodes[(r["concept_id"], r["wave_id"], r["q_id"])].append(
                (int(r["option_id"]), r["concept_option_id"])
            )

    # --- catálogo canónico + mapa de opciones --------------------------------
    # Sólo para conceptos CATEGÓRICOS: los numéricos se alinean por VALOR en la
    # vista Año, así que un catálogo de opciones canónicas no significa nada.
    # El catálogo es la UNIÓN de las opciones de las olas miembro (gana la
    # etiqueta de la ola más reciente); los centinelas se normalizan al código
    # estándar. Una ola cubierta por un recode NO aporta al catálogo: contribuye
    # sólo las equivalencias que el recode declara.
    catalog, opt_map = [], []
    for cid, nodes in members.items():
        if concepts[cid]["q_type"] != "categorica":
            continue
        native = [
            n
            for n in nodes
            if (cid, n[0], n[1]) not in recodes
            and qtype.get(n) == "categorica"
            and opts.get(n)
        ]
        real, sentinels = {}, {}
        for n in sorted(native):  # ola ascendente → gana la más nueva
            for oid, olabel in opts[n].items():
                if _is_sentinel(oid, olabel):
                    sentinels[_sentinel_kind(olabel)] = SENT_CANON[
                        _sentinel_kind(olabel)
                    ]
                else:
                    real[oid] = olabel
        for oid in sorted(real):
            catalog.append((cid, f"{cid}:{oid}", real[oid], oid))
        for _, (code, olabel) in sorted(sentinels.items(), key=lambda kv: kv[1][0]):
            catalog.append((cid, f"{cid}:{code}", olabel, code))
        for n in native:
            for oid, olabel in opts[n].items():
                code = (
                    SENT_CANON[_sentinel_kind(olabel)][0]
                    if _is_sentinel(oid, olabel)
                    else oid
                )
                opt_map.append((n[0], n[1], oid, f"{cid}:{code}"))

    known_options = {c[1] for c in catalog}
    for (cid, wave, qid), rs in recodes.items():
        if cid not in members:
            warnings.append(
                f"recode hacia un concepto inexistente: {cid} ({wave}/{qid})"
            )
            continue
        for oid, coid in rs:
            if coid not in known_options:
                # Opción SIN equivalente en las otras olas (p. ej. "Todos los
                # anteriores", que sólo existió en 2024). El recode le declara un
                # id propio y aquí entra al catálogo con su etiqueta real: sin
                # esto el motor cae al fallback `{cid}:{código}` y la funde con la
                # opción que use ese MISMO código en otra ola, aunque signifiquen
                # cosas distintas. Si la ola tampoco tiene esa opción, entonces sí
                # es un id mal escrito y se avisa como antes.
                label = opts.get((wave, qid), {}).get(oid)
                if label is None:
                    warnings.append(
                        f"recode hacia una opción canónica inexistente: {coid}"
                    )
                else:
                    catalog.append((cid, coid, label, oid))
                    known_options.add(coid)
            opt_map.append((wave, qid, oid, coid))

    # --- avisos de integridad -------------------------------------------------
    for a, b, note in excluded_pairs:
        ca, cb = (
            next((c for c, ms in members.items() if n in ms), None) for n in (a, b)
        )
        if ca and ca == cb:
            warnings.append(
                f"par EXCLUIDO que quedó en el mismo concepto por transitividad: "
                f"{a[0]}/{a[1]} ↔ {b[0]}/{b[1]} ({note}) → {ca}"
            )

    # --- escribir a la BD -----------------------------------------------------
    con.executemany(
        "INSERT INTO concepts (concept_id, label, q_type) VALUES (?,?,?)",
        [(c["concept_id"], c["label"], c["q_type"]) for c in concepts.values()],
    )
    con.executemany(
        "UPDATE questions SET concept_id = ? WHERE wave_id = ? AND q_id = ?",
        [(cid, w, q) for cid, ns in members.items() for w, q in ns],
    )
    if catalog:
        con.executemany(
            "INSERT INTO concept_options (concept_id, concept_option_id, label, sort_order)"
            " VALUES (?,?,?,?)",
            catalog,
        )
    if opt_map:
        con.executemany(
            "UPDATE options SET concept_option_id = ? "
            "WHERE wave_id = ? AND question_id = ? AND option_id = ?",
            [(coid, w, q, oid) for w, q, oid, coid in opt_map],
        )

    n_linked = con.execute(
        "SELECT COUNT(*) FROM questions WHERE concept_id IS NOT NULL"
    ).fetchone()[ # type: ignore
        0
    ]  # type: ignore
    by_type = Counter(c["q_type"] for c in concepts.values())
    print(
        f"  pares: {len(rows)} renglones ({skipped} de olas no cargadas, "
        f"{len(excluded_pairs)} excluidos; {skipped_recodes} recodes de olas no cargadas)"
    )
    print(
        f"  conceptos={len(concepts)} ({dict(by_type)})  preguntas enlazadas={n_linked}  "
        f"opciones canónicas={len(catalog)}  recodes={sum(len(v) for v in recodes.values())}"
    )
    if warnings:
        print(f"  ⚠️  {len(warnings)} avisos de armonización:")
        for wave in warnings[:15]:
            print(f"     · {wave}")
        if len(warnings) > 15:
            print(f"     … y {len(warnings) - 15} más")


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------
def _validate(con: duckdb.DuckDBPyConnection) -> None:
    print("\nValidación:")
    ok = True

    # Conteo de olas
    waves = [
        r[0]
        for r in con.execute("SELECT wave_id FROM waves ORDER BY wave_id").fetchall()
    ]
    print(f"  olas cargadas: {waves}")

    for w in waves:
        # Unicidad de (wave, respondent, question) en answers (no hay PK).
        dups = con.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT respondent_id, question_id, COUNT(*) n
                FROM answers WHERE wave_id = ? GROUP BY 1, 2 HAVING n > 1
            )
            """,
            [w],
        ).fetchone()[ # type: ignore
            0
        ]  # type: ignore
        # Integridad: exactamente uno de (option_id, value).
        bad = con.execute(
            """
            SELECT COUNT(*) FROM answers WHERE wave_id = ?
            AND ((option_id IS NULL AND value IS NULL)
                 OR (option_id IS NOT NULL AND value IS NOT NULL))
            """,
            [w],
        ).fetchone()[ # type: ignore
            0
        ]  # type: ignore
        n_ans = con.execute("SELECT COUNT(*) FROM answers WHERE wave_id = ?", [w]).fetchone()[0]  # type: ignore
        n_resp = con.execute("SELECT COUNT(*) FROM responses WHERE wave_id = ?", [w]).fetchone()[0]  # type: ignore
        print(
            f"  [{w}] responses={n_resp:>6,}  answers={n_ans:>9,}  "
            f"dups={dups}  eav_malformadas={bad}  "
            f"{'OK' if dups == 0 and bad == 0 else 'FALLA'}"
        )
        ok = ok and dups == 0 and bad == 0

    if not ok:
        con.close()
        sys.exit("ERROR: la validación falló.")


# ---------------------------------------------------------------------------
def main() -> None:
    if not SRC_2025.exists():
        sys.exit(f"ERROR: no existe la BD origen 2025: {SRC_2025}")
    if not SCHEMA.exists():
        sys.exit(f"ERROR: no existe el esquema: {SCHEMA}")

    if DST.exists():
        DST.unlink()  # reconstrucción limpia

    con = duckdb.connect(str(DST), config={"memory_limit": "256MB", "threads": 2})
    try:
        _run_schema(con)
        con.execute(f"ATTACH '{SRC_2025}' AS src (READ_ONLY)")
        load_wave_2025(con)
        con.execute("DETACH src")

        load_wave_csv(con, "2024", 2024, "Así Vamos 2024")
        load_wave_csv(con, "2023", 2023, "Así Vamos 2023")
        load_wave_csv(con, "2022", 2022, "Así Vamos 2022")
        load_wave_csv(con, "2021", 2021, "Así Vamos 2021")
        if feature("olas_2016_2019"):
            load_wave_csv(con, "2019", 2019, "Así Vamos 2019")
            load_wave_csv(con, "2018", 2018, "Así Vamos 2018")
            load_wave_csv(con, "2017", 2017, "Así Vamos 2017")
            load_wave_csv(con, "2016", 2016, "Así Vamos 2016")
        else:
            print("\n· Olas 2016–2019 omitidas (flag olas_2016_2019 apagado)")

        apply_question_fixes(con)
        apply_option_fixes(con)
        apply_question_type_fixes(con)
        load_concepts(con)

        _validate(con)
    finally:
        con.close()

    size_mb = DST.stat().st_size / 1_048_576
    print(f"\n✓ BD multi-año construida: {DST}  ({size_mb:.1f} MB)")
    print(f"  Original intacta:        {SRC_2025}")


if __name__ == "__main__":
    main()
