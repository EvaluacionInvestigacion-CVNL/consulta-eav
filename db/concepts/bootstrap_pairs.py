#!/usr/bin/env python3
"""Borrador de equivalencias entre olas — HERRAMIENTA MANUAL, no parte del build.

Al cargar una ola nueva hay que decirle a `build_db.py` qué pregunta de esa ola
equivale a cuál de la ola anterior (`db/concepts/concept_equivalences.csv`). Ese
archivo se mantiene A MANO. Este script sólo redacta un BORRADOR para no partir
de una hoja en blanco: propone pares por similitud de texto, y el equipo revisa,
corrige y pega lo que sea correcto.

    .venv/bin/python db/concepts/bootstrap_pairs.py --new 2026
    .venv/bin/python db/concepts/bootstrap_pairs.py --new 2026 --against 2024

Escribe `db/concepts/concept_equivalences.draft.csv` (mismo esquema que el
archivo real, con `source=draft`). NADA de esto entra a la BD hasta que alguien
mueva los renglones al archivo real. Los pares que ya existen se omiten.

IMPORTANTE: la similitud de texto se equivoca — junta baterías distintas y
separa preguntas que sólo cambiaron de redacción. Por eso es un borrador para
revisar, no una fuente de verdad. Cada renglón trae `sim` (0-1) para priorizar
la revisión: lo que está cerca del umbral casi siempre necesita ojo humano.
"""

import argparse
import csv
import difflib
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "encuesta_multianual.duckdb"
EQUIV = Path(__file__).resolve().parent / "concept_equivalences.csv"
OUT = Path(__file__).resolve().parent / "concept_equivalences.draft.csv"

TH = 0.62  # umbral de similitud (igual que el emparejador histórico)
FIELDS = ["wave_a", "q_a", "wave_b", "q_b", "ctype", "decision", "concept_id", "source", "note", "reason"]


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\b(cp|p)\s*\d+(\s*[_\s]\s*\d+)*\b", " ", t)      # códigos de pregunta
    t = re.sub(r"\bnombre del estudiante\b|\bnombre\b|\(nombre\)|\[[^\]]*\]", " ", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _sim(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    seq = difflib.SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    return 0.5 * seq + 0.5 * len(ta & tb) / max(len(ta | tb), 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", required=True, help="ola nueva, p. ej. 2026")
    ap.add_argument("--against", help="ola de referencia (default: la más reciente anterior)")
    ap.add_argument("--threshold", type=float, default=TH)
    args = ap.parse_args()

    con = duckdb.connect(str(DB), read_only=True)
    waves = [r[0] for r in con.execute("SELECT wave_id FROM waves ORDER BY wave_id").fetchall()]
    if args.new not in waves:
        raise SystemExit(f"ERROR: la ola {args.new} no está cargada en la BD. Olas: {waves}")
    ref = args.against or max((w for w in waves if w < args.new), default=None)
    if not ref:
        raise SystemExit(f"ERROR: no hay ola anterior contra la cual comparar. Olas: {waves}")

    questions = defaultdict(dict)
    for w, q, txt, qt in con.execute(
        "SELECT wave_id,q_id,q_text,q_type FROM questions WHERE wave_id IN (?,?)", [args.new, ref]
    ).fetchall():
        questions[w][q] = ((txt or ""), (qt or ""))
    # los atributos llevan un nombre estable entre olas → equivalencia CIERTA
    attrs = defaultdict(dict)
    for w, a, q in con.execute(
        "SELECT DISTINCT wave_id,attribute,question_id FROM respondent_attributes "
        "WHERE wave_id IN (?,?)", [args.new, ref]
    ).fetchall():
        attrs[a][w] = q
    con.close()

    existing = set()
    if EQUIV.exists():
        for r in csv.DictReader(EQUIV.open()):
            existing.add(frozenset([(r["wave_a"], r["q_a"]), (r["wave_b"], r["q_b"])]))

    rows, paired = [], set()

    # 1) semilla exacta por nombre de atributo
    for attr, byw in sorted(attrs.items()):
        if ref in byw and args.new in byw:
            a, b = (ref, byw[ref]), (args.new, byw[args.new])
            if frozenset([a, b]) in existing:
                continue
            paired |= {byw[ref], byw[args.new]}
            rows.append({
                "wave_a": ref, "q_a": byw[ref], "wave_b": args.new, "q_b": byw[args.new],
                "ctype": questions[args.new].get(byw[args.new], ("", "categorica"))[1] or "categorica",
                "decision": "comparable", "concept_id": f"attr_{attr}", "source": "draft",
                "note": f"atributo '{attr}' (nombre estable entre olas · sim=1.00)",
            })

    # 2) mejor match MUTUO por texto para el resto
    A = {q: v for q, v in questions[ref].items() if q not in paired}
    B = {q: v for q, v in questions[args.new].items() if q not in paired}
    best_ab = {qa: max(B, key=lambda qb: _sim(A[qa][0], B[qb][0]), default=None) for qa in A}
    best_ba = {qb: max(A, key=lambda qa: _sim(B[qb][0], A[qa][0]), default=None) for qb in B}
    for qa, qb in best_ab.items():
        if not qb or best_ba.get(qb) != qa:
            continue
        s = _sim(A[qa][0], B[qb][0])
        if s < args.threshold:
            continue
        if frozenset([(ref, qa), (args.new, qb)]) in existing:
            continue
        rows.append({
            "wave_a": ref, "q_a": qa, "wave_b": args.new, "q_b": qb,
            "ctype": B[qb][1] or "categorica", "decision": "comparable",
            "concept_id": "", "source": "draft",
            "note": f"sim={s:.2f} · REVISAR · {_norm(A[qa][0])[:60]}",
            "reason": "",
        })

    rows.sort(key=lambda r: (r["source"], r["note"]))
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    unmatched = sorted(set(B) - {r["q_b"] for r in rows})
    print(f"olas: {ref} → {args.new}   (umbral {args.threshold})")
    print(f"pares propuestos : {len(rows)}  →  {OUT.relative_to(ROOT)}")
    print(f"ya en el archivo : {len(existing)} pares (omitidos)")
    print(f"sin pareja en {args.new}: {len(unmatched)} preguntas {unmatched[:12]}")
    print("\nRevisar el borrador y mover los renglones correctos a "
          f"{EQUIV.relative_to(ROOT)} (cambiando source=draft por source=manual);")
    print("luego reconstruir:  .venv/bin/python db/build_db.py")


if __name__ == "__main__":
    main()
