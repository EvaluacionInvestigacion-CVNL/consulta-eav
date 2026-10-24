#!/usr/bin/env python3
"""Capa B — genera `options_fixes_approved.csv` (overlay de etiquetas de opción).

Cruza, por ola, el CUESTIONARIO original (`data/source/{año}/Cuestionario {año}.xlsx`) con
los códigos que aparecen en `answers` pero faltan en el catálogo `options`
(huecos que, sin reparar, obligan al motor a mostrarlos como "Código N"). Para
cada hueco decide una etiqueta:

  1. (q,code) en SPECIAL         -> etiqueta a mano (celdas corruptas de la fuente)
  2. code en cuestionario c/texto -> ese texto
  3. code en cuestionario s/texto -> el número (punto de escala 1-10)
  4. centinela (convención x ola) -> No sabe / No contesta / No aplica
  5. code > máx opción real       -> "Otro" (specs de "Otro*" auto-numeradas)
  6. resto                        -> "Otro"

Además emite RELABEL: etiquetas que YA existen en `options` y se corrigen a mano
(no son huecos), por lo que no sobrevivirían si sólo se escribieran en el CSV.

El resultado lo consume `db/build_db.py::apply_option_fixes` con semántica upsert,
SIN tocar las fuentes crudas. Regenerar tras cambiar un cuestionario o un SPECIAL:

    .venv/bin/python db/overlays/build_option_fixes.py

Notas de formato del cuestionario (difiere por año):
  - 2021: q_id en col 8; opciones como "Respuestas N: <código>. <texto>". OJO:
    los ORDINALES no son los códigos (cp8_1: "Respuestas 9: 10. ...") y a veces
    hay un q_id espurio en la fila de opción -> no se reasigna la pregunta ahí.
  - 2022: q_id en col 1 (mayúsculas -> minúsculas); opciones "N. <texto>" en col 2.
  - 2024/2023: q_id en col 2; opciones "N. <texto>" en col 3.
  - 2025: se carga desde la BD de una ola; sin cuestionario -> sólo centinelas.
"""
import csv, re
from collections import defaultdict
from pathlib import Path

import duckdb
import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DB = ROOT / "data" / "encuesta_multianual.duckdb"       # answers (crudas)
WAVES_DIR = ROOT / "data" / "waves"                      # catálogo crudo por ola
SRC_2025 = WAVES_DIR / "2025" / "encuesta.duckdb"       # catálogo crudo 2025
OUT = HERE / "options_fixes_approved.csv"

SENT_2021 = {8: "No sabe", 9: "No contesta", 88: "No sabe",
             98: "No sabe/No contesta", 99: "No aplica",
             888: "No sabe", 999: "No contesta"}
SENT_STD = {7777: "No aplica", 8888: "No sabe", 9999: "No contesta",
            888: "No sabe", 999: "No contesta", 998: "No contesta"}

SPECIAL = {  # (wave,q,code) -> etiqueta a mano (fuente corrupta / sin código explícito)
    ("2021", "p58", 0): "No",
    ("2021", "p128", 13): "No contesta",
    ("2021", "p81_a", 96): "No aplica",
    ("2021", "p81_b", 96): "No aplica",
    ("2021", "p81_c", 96): "No aplica",
    ("2021", "p12", 14): "No utilizó estos modos",
    ("2021", "p12", 15): "Otro. Explicar",
    **{("2021", "p8", c): str(c) for c in range(1, 8)},
    ("2024", "p158_2", 0): "No",
    ("2024", "p68", 2): "Mayor consumo de electricidad",
    ("2024", "p112_2", 1): "Sí",
    ("2022", "p124", 8): "6-7 SM ($31,116 - $36,302)",
}

RELABEL = {  # (wave,q,code) -> etiqueta que CORRIGE una ya existente (no es un hueco)
    # "No sabe qué hacer en esos casos" es una respuesta sustantiva (225 casos,
    # 7.55 % ponderado: qué hace la gente ante la mala calidad del aire), pero la
    # regla de centinela por etiqueta —`no\s*(sabe|contest|aplica|respond)`, en
    # db/build_db.py::_is_sentinel y en services/query/sentinels.py— la leería como
    # "No sabe" y la normalizaría a 8888. Hoy es inocuo porque 2025 p75 no tiene
    # concepto; el día que se declare el par, esos 225 casos desaparecerían del
    # promedio sin que nada avise. Se corrige la etiqueta ANTES de declarar el par.
    ("2025", "p75", 4): "No tiene claro qué hacer",
    # Categoría sustantiva con código 6666 dentro de una escala 1-10 que 2024
    # guardó como `categorica`: la vista Año toma el option_id COMO VALOR, así que
    # ese único caso (ponderado 667) subía la media de 2024 de 8.22 a 9.21 en
    # c2025_p62_5. No es un "no sabe" y ningún filtro por magnitud debe tocarlo
    # (el techo de escala es inconfiable), así que el arreglo es la etiqueta: con
    # "No aplica" delante, year_comparison.is_sentinel_label lo saca del promedio
    # y lo deja visible como renglón en los conteos.
    ("2024", "p52_5", 6666): "No aplica: no cuenta con servicio de recolección de residuos",
}

# (qid_col, opt_col, lower_qid, style); style "respuestas" vs "qidcol"
WAVE_CFG = {
    "2021": (8, 2, False, "respuestas", SENT_2021),
    "2022": (1, 2, True, "qidcol", SENT_STD),
    "2024": (2, 3, False, "qidcol", SENT_STD),
    "2023": (2, 3, False, "qidcol", SENT_STD),
    "2025": (None, None, False, None, SENT_STD),  # sin cuestionario
}

_RESP = re.compile(r"Respuestas\s*(\d+)\s*:\s*(.*)", re.I | re.S)
# código explícito al inicio: "N.", "N)" o "N" pelón (escala). Texto que empieza
# con letra ("Otro...", "No utilizó...") NO matchea -> se salta (ordinal no fiable).
_CODE = re.compile(r"^\s*(-?\d+)\s*[.)]?\s*(.*)", re.S)


def parse_questionnaire(wave):
    """Devuelve (Q, OTRO): Q[qid]={code:label} de opciones con código explícito;
    OTRO = set de qids que traen una opción "Otro" SIN numerar (su código real lo
    auto-asigna el ETL a un número pasado del máximo -> se etiqueta 'Otro')."""
    qc, oc, low, style, _ = WAVE_CFG[wave]
    xlsx = ROOT / "data" / "source" / wave / f"Cuestionario {wave}.xlsx"
    Q = defaultdict(dict)
    OTRO = set()
    if style is None or not xlsx.exists():
        return Q, OTRO
    ws = openpyxl.load_workbook(xlsx, read_only=True, data_only=True).worksheets[0]
    cur = None
    for row in ws.iter_rows(values_only=True):
        if style == "respuestas":
            txt = str(row[oc]).strip() if len(row) > oc and row[oc] else ""
            m = _RESP.match(txt)
            if not m:                                  # fila de pregunta -> fija cur
                qid = row[qc] if len(row) > qc else None
                if qid and str(qid).strip():
                    cur = str(qid).strip()
                continue
            if not cur:
                continue
            rest = m.group(2).strip()
        else:  # qidcol
            qid = row[qc] if len(row) > qc else None
            if qid and str(qid).strip():
                cur = str(qid).strip().lower().replace(" ", "") if low else str(qid).strip()
                continue
            rest = str(row[oc]).replace("\xa0", " ").strip() if len(row) > oc and row[oc] else ""
            if not cur:
                continue
        if re.match(r"(?i)^otro", rest):
            OTRO.add(cur)
            continue
        if not re.match(r"^\s*-?\d", rest):
            continue
        cm = _CODE.match(rest)
        if cm:
            Q[cur][int(cm.group(1))] = cm.group(2).strip().rstrip("*").strip()
    return Q, OTRO


def raw_catalog():
    """Catálogo CRUDO por (wave,q) -> {code} desde las fuentes (no la BD ya
    construida, que trae el overlay). 2021-2024: data/waves/*/options.csv; 2025:
    data/waves/2025/encuesta.duckdb."""
    cat = defaultdict(set)
    for wave in ["2021", "2022", "2023", "2024"]:
        f = WAVES_DIR / wave / "options.csv"
        for r in csv.DictReader(open(f)):
            cat[(wave, r["question_id"])].add(int(r["option_id"]))
    src = duckdb.connect(str(SRC_2025), read_only=True)
    for q, oid in src.execute("SELECT question_id, option_id FROM options").fetchall():
        cat[("2025", q)].add(int(oid))
    src.close()
    return cat


def discover_gaps(con, cat):
    """Códigos que aparecen en answers (categóricas, iniciales) pero NO en el
    catálogo crudo -> los huecos que la Capa B debe etiquetar."""
    rows = con.execute(
        """
        SELECT a.wave_id, a.question_id, a.option_id
        FROM answers a
        JOIN responses r ON r.wave_id=a.wave_id AND r.respondent_id=a.respondent_id
                        AND r.is_initial_respondent=1
        JOIN questions q ON q.wave_id=a.wave_id AND q.q_id=a.question_id
                        AND q.q_type='categorica'
        WHERE a.option_id IS NOT NULL
        GROUP BY 1,2,3
        """
    ).fetchall()
    gaps = defaultdict(list)   # wave -> [(q,code)]
    for w, q, code in rows:
        if int(code) not in cat[(w, q)]:
            gaps[w].append((q, int(code)))
    return gaps


def main():
    con = duckdb.connect(str(DB), read_only=True)
    cat = raw_catalog()
    gaps = discover_gaps(con, cat)

    rows = []
    for wave in ["2021", "2022", "2023", "2024", "2025"]:
        Q, OTRO = parse_questionnaire(wave)
        sent = WAVE_CFG[wave][4]

        def real_max(q):
            ks = [c for c in set(Q[q]) | cat[(wave, q)] if c < 90]
            return max(ks) if ks else -1

        for q, code in gaps[wave]:
            rmax = real_max(q)
            if (wave, q, code) in SPECIAL:
                lab = SPECIAL[(wave, q, code)]
            elif code in Q[q] and Q[q][code]:
                lab = Q[q][code]
            elif code in Q[q]:
                lab = str(code)                        # escala
            elif q in OTRO and rmax < code < 88:
                lab = "Otro"                           # opción "Otro" auto-numerada
            elif code in sent and (code >= 88 or code > rmax):
                lab = sent[code]
            else:
                lab = "Otro"
            rows.append((wave, q, code, lab))

    # Correcciones a mano de etiquetas que SÍ existen (no son huecos): sobreescriben
    # lo que haya salido arriba y se emiten aunque el código no esté en `gaps`.
    rows = [r for r in rows if (r[0], r[1], r[2]) not in RELABEL]
    rows.extend((w, q, c, lab) for (w, q, c), lab in RELABEL.items())

    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["wave_id", "question_id", "option_id", "option_label"])
        w.writerows(rows)
    print(f"✓ {len(rows)} reparaciones -> {OUT.relative_to(ROOT)}")
    from collections import Counter
    print("  por ola:", dict(Counter(r[0] for r in rows)))


if __name__ == "__main__":
    main()
