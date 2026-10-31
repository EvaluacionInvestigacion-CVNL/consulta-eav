"""Invariantes de la capa de conceptos (armonización entre olas).

`test_db_freshness.py` verifica que la BD **refleje** los insumos hechos a mano.
Estos tests verifican algo distinto: que los insumos sean **coherentes**, es
decir que las declaraciones de `db/concepts/*.csv` no produzcan una serie de
tiempo falsa. Existen porque los tres modos de falla de esta capa son
silenciosos —el build avisa pero no falla, y la vista Año publica el número
igual—:

1. **Colisión por el fallback.** Cuando una opción no tiene opción canónica,
   `_year_comparison` cae a `f"{concept_id}:{option_id}"`. Dos olas que usan el
   MISMO código para respuestas distintas quedan fundidas en un solo renglón sin
   ninguna señal (es el caso que motivó los recodes: "NO HAY"=3 en 2021 contra
   "No hay"=2 en 2022, o el Covid=3 de 2021 contra "salud mental"=3 de 2025).
2. **Recode incompleto.** Una ola cubierta por un recode aporta EXACTAMENTE lo
   declarado; lo que se omite vuelve al fallback del punto 1.
3. **Centinela dentro del promedio.** En un concepto `numerica`, la ola que
   guardó la escala como `categorica` aporta su `option_id` como valor, así que
   los códigos 88/98/99/888/999 ("No sabe"/"No contesta") entran a la media.

Ninguno de los tres rompe nada visible: el resultado sigue siendo un número
plausible en una tabla. Por eso se testean.
"""

import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EQUIV = ROOT / "db" / "concepts" / "concept_equivalences.csv"
RECODES = ROOT / "db" / "concepts" / "concept_recodes_approved.csv"

# Códigos-centinela que la vista Año ya descarta del promedio
# (services.query.sentinels.YEAR_VIEW_SENTINEL_CODES).
YEAR_SENTINELS = {7777, 8888, 9999, 5555}

# Etiquetas "Otro" que no identifican una respuesta: casi todas las olas
# arrastran varias con códigos distintos, así que verlas en dos códigos
# distintos NO indica que la opción se haya movido de código.
OTRO_RE = re.compile(r"^(otro|otra|otros|ninguno|ninguna|na)\b|^\d+$")

# Reconocimiento de centinelas REIMPLEMENTADO a propósito, igual que
# `_declared_partition` en test_db_freshness.py: si estos tests importaran
# `_is_sentinel` de db/build_db.py, un bug de esa función se volvería invisible
# aquí (y es justo la función que decide qué entra al catálogo canónico).
# Códigos estándar del app + etiqueta explícita + las SIGLAS que sólo usa 2021.
SENT_CODES = {7777, 8888, 9999}
SENT_LABEL_RE = re.compile(r"no\s*(sabe|contest|aplica|respond)", re.I)
SENT_ABBR_RE = re.compile(r"^\s*(NS\s*/\s*NC|NS|NC|NA)\s*$", re.I)


def _es_centinela(option_id, label):
    texto = str(label or "")
    return (
        option_id in SENT_CODES
        or bool(SENT_LABEL_RE.search(texto))
        or bool(SENT_ABBR_RE.match(texto))
    )


REVISAR = (
    "Revisa la declaración en db/concepts/ y reconstruye:\n"
    "    .venv/bin/python db/build_db.py"
)


def _rows(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def _norm(s):
    """Etiqueta normalizada para comparar entre olas: sin acentos, sin el
    prefijo de viñeta ('A. ', 'H: ') y sin puntuación."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"^\s*[a-z]\s*[.:)]\s*", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


@pytest.fixture(scope="module")
def conn():
    import db_runtime

    c = db_runtime.get_conn()
    yield c
    c.close()


@pytest.fixture(scope="module")
def hechos(conn):
    """Los hechos de la BD que estos tests consultan una y otra vez."""
    qtype, qconcept = {}, {}
    for w, q, t, cid in conn.execute(
        "SELECT wave_id, q_id, q_type, concept_id FROM questions"
    ).fetchall():
        qtype[(w, q)] = t or ""
        qconcept[(w, q)] = cid
    opts = defaultdict(dict)
    for w, q, o, lbl in conn.execute(
        "SELECT wave_id, question_id, option_id, option_label FROM options"
    ).fetchall():
        opts[(w, q)][o] = lbl or ""
    casos = defaultdict(dict)
    for w, q, o, n in conn.execute(
        "SELECT wave_id, question_id, option_id, count(*) FROM answers "
        "WHERE option_id IS NOT NULL GROUP BY 1, 2, 3"
    ).fetchall():
        casos[(w, q)][o] = n
    concepts = {
        cid: t
        for cid, t in conn.execute("SELECT concept_id, q_type FROM concepts").fetchall()
    }
    members = defaultdict(list)
    for w, q, cid in conn.execute(
        "SELECT wave_id, q_id, concept_id FROM questions WHERE concept_id IS NOT NULL"
    ).fetchall():
        members[cid].append((w, q))
    return dict(
        qtype=qtype, qconcept=qconcept, opts=opts, casos=casos,
        concepts=concepts, members=members,
    )


# ---------------------------------------------------------------------------
# 1. El `ctype` declarado tiene que ser compatible con el q_type de las olas
# ---------------------------------------------------------------------------


def test_toda_exclusion_tiene_motivo_publicable():
    """Cada par `exclude` lleva un `reason` del vocabulario de
    `metadata.EXCLUSION_REASONS`: es lo que la UI le explica al usuario cuando
    una pregunta no se compara entre años. La `note` es técnica y no se publica."""
    from metadata import EXCLUSION_REASONS

    sin_motivo = [
        f"{r['wave_a']}/{r['q_a']} <-> {r['wave_b']}/{r['q_b']}: {r.get('reason')!r}"
        for r in _rows(EQUIV)
        if r["decision"] == "exclude" and r.get("reason") not in EXCLUSION_REASONS
    ]
    assert not sin_motivo, (
        f"{len(sin_motivo)} exclusiones sin motivo valido "
        f"(usa uno de {sorted(EXCLUSION_REASONS)}): {sin_motivo[:5]}"
    )


def test_ningun_concepto_categorico_tiene_miembro_numerico(hechos):
    """Si una ola guardó la medida en `answers.value`, el concepto NO puede ser
    `categorica`.

    El camino categórico de `_year_comparison` lee cada renglón del path plano
    como `(option_id, etiqueta, conteo)`, pero una pregunta `numerica` devuelve
    `(valor, conteo, porcentaje)`. Esa ola aportaría el CONTEO como etiqueta y
    el PORCENTAJE como conteo: la columna de ese año sale con números que
    parecen datos y no lo son. La regla es unidireccional a propósito — un
    concepto `numerica` con un miembro `categorica` sí funciona (la vista Año
    alinea por valor), y de hecho es el caso normal de las escalas 1-10."""
    malos = [
        (cid, w, q)
        for cid, ms in hechos["members"].items()
        if hechos["concepts"][cid] == "categorica"
        for w, q in ms
        if hechos["qtype"][(w, q)] == "numerica"
    ]
    assert not malos, (
        "concepto declarado 'categorica' con un miembro guardado como 'numerica' "
        f"(la columna de ese año saldría corrupta): {malos}\n"
        f"  Arreglo: pon ctype=numerica en el renglón de concept_equivalences.csv, "
        f"o declara el par 'exclude' si no son la misma medida.\n  {REVISAR}"
    )


# E6 CERRADO: `2024 p52_5` código 6666 = 'No cuento con el servicio de recolección
# de residuos en mi hogar.' (n=1, ponderado 667) vivía dentro de la escala 1-10 de
# `c2025_p62_5` y entraba a la media de la vista Año como si fuera una calificación:
# 9.21 contra 8.22 sin él. No es un centinela —es una categoría sustantiva— así que
# el arreglo NO podía ser un filtro por magnitud: se re-etiquetó a 'No aplica: no
# cuenta con servicio de recolección de residuos' en db/overlays (RELABEL de
# build_option_fixes.py + el renglón del CSV), con lo que `is_sentinel_label` lo saca
# del promedio y lo deja visible como renglón en los conteos. La serie quedó
# 8.05 / 8.50 / 8.26 / 8.22 / 8.69. Este test era `xfail(strict=True)` para forzar
# justo esto: al arreglarse, el XPASS rompió la suite y obligó a quitar el marcador.
# Ahora es un guard vivo.
def test_miembro_categorico_de_concepto_numerico_es_escala_pura(hechos):
    """La dirección espejo del test anterior, acotada a donde de verdad hace daño.

    Un concepto `numerica` con un miembro `categorica` es el caso NORMAL (una
    escala 1-10 que una ola guardó como catálogo de opciones), así que exigir que
    los tipos coincidan sería puro ruido: hoy hay 21 conceptos así y todos son
    legítimos. Pero la vista Año toma el `option_id` de esa ola COMO VALOR, y eso
    sólo es correcto si el catálogo es la escala y nada más. El criterio, por eso,
    no es el tipo sino la forma del catálogo:

    - **legítimo**: una binaria 0/1 (la media es una proporción) o una escala
      cuyas etiquetas son el número mismo (`'1'`, `'2'`, … `'10'`);
    - **ilegítimo**: la escala con una categoría de texto colada dentro, porque
      entonces el CÓDIGO de esa categoría (6666, 96, …) se promedia junto a las
      calificaciones y mueve la media sin que nada se vea raro.

    Complementa a `test_conceptos_numericos_son_escalas_no_nominales`, que sólo
    rechaza el catálogo enteramente nominal; éste rechaza el catálogo MIXTO, que
    es el que pasa desapercibido. Sólo se miran las opciones CON casos: una opción
    vacía no entra a ninguna media.

    Advertencia para quien lo lea buscando el caso de `c2025_cp19`: ese defecto
    (2023 cp16_1, que es Primaria, colgado de la satisfacción general de 2025) era
    **semántico**, no de tipos — su catálogo es una escala 1-10 impecable — y este
    test tampoco lo habría visto. Lo que lo cerró fue leer los dos `q_text`.
    """
    sucias = []
    for cid, ms in sorted(hechos["members"].items()):
        if hechos["concepts"][cid] != "numerica":
            continue
        for w, q in sorted(ms):
            if hechos["qtype"][(w, q)] != "categorica":
                continue
            con_casos = hechos["casos"].get((w, q), {})
            sustantivas = {
                o: lbl
                for o, lbl in hechos["opts"].get((w, q), {}).items()
                if o not in YEAR_SENTINELS
                and not _es_centinela(o, lbl)
                and con_casos.get(o, 0) > 0
            }
            if not sustantivas or set(sustantivas) <= {0, 1}:
                continue  # sin datos, o binaria: la media es una proporción
            impuras = sorted(
                (o, lbl, con_casos[o])
                for o, lbl in sustantivas.items()
                if str(lbl).strip().replace(".", "") != str(o)
            )
            if impuras:
                sucias.append((cid, w, q, impuras[:3]))
    assert not sucias, (
        "concepto 'numerica' cuyo miembro categórico NO es una escala pura: el "
        "código de una categoría de texto entra al 'Promedio (media)' de la vista "
        "Año como si fuera una calificación.\n"
        + "\n".join(
            f"  {cid} ({w}/{q}): " + ", ".join(f"{o}={lbl!r} (n={n})" for o, lbl, n in ej)
            for cid, w, q, ej in sucias
        )
        + "\n  Arreglo: si es un centinela, re-etiquétalo/muévelo al código estándar "
        "en db/overlays/options_fixes_approved.csv; si es una categoría real, el "
        "concepto no puede ser 'numerica' con esa ola dentro.\n"
        f"  {REVISAR}"
    )


# ---------------------------------------------------------------------------
# 2. Ninguna respuesta cae al fallback `{concept_id}:{código}`
# ---------------------------------------------------------------------------


def test_toda_opcion_con_casos_tiene_opcion_canonica(hechos):
    """En un concepto CATEGÓRICO, toda opción con al menos una respuesta debe
    tener `concept_option_id`.

    Sin él, `_year_comparison` inventa `f"{concept_id}:{option_id}"` y funde esa
    respuesta con la que usa el MISMO código en otra ola, aunque signifiquen
    cosas distintas — el error se publica como una serie continua. Sólo se
    exigen las opciones CON casos: una opción declarada y vacía no puede
    producir renglón, así que no puede colisionar (es el caso deliberado de
    `attr_sexo:3` "No binario", documentado en docs/conceptos.md).

    Los conceptos `numerica` quedan fuera a propósito: no arman catálogo porque
    la vista Año los alinea por VALOR, no por opción canónica."""
    import db_runtime

    c = db_runtime.get_conn()
    try:
        huerfanas = c.execute(
            """
            SELECT o.wave_id, o.question_id, o.option_id, o.option_label, q.concept_id
            FROM options o
            JOIN questions q ON q.wave_id = o.wave_id AND q.q_id = o.question_id
            JOIN concepts cc ON cc.concept_id = q.concept_id
            WHERE o.concept_option_id IS NULL
              AND cc.q_type = 'categorica'
              AND EXISTS (SELECT 1 FROM answers a
                          WHERE a.wave_id = o.wave_id
                            AND a.question_id = o.question_id
                            AND a.option_id = o.option_id)
            ORDER BY 1, 2, 3
            """
        ).fetchall()
    finally:
        c.close()
    assert not huerfanas, (
        "opciones CON respuestas y sin opción canónica: la vista Año las funde con "
        "la opción que use ese mismo código en otra ola.\n"
        f"  (ola, pregunta, código, etiqueta, concepto): {huerfanas[:8]}\n"
        "  Arreglo: agrega el renglón en concept_recodes_approved.csv apuntando a la "
        "opción canónica correcta (o a un id propio, p. ej. ':otro_2021', si no tiene "
        f"equivalente).\n  {REVISAR}"
    )


# ---------------------------------------------------------------------------
# 3. Los recodes son exhaustivos para la ola que cubren
# ---------------------------------------------------------------------------


def test_recodes_exhaustivos(hechos):
    """Una ola cubierta por un recode aporta EXACTAMENTE lo declarado.

    `load_concepts` saca del catálogo canónico a la pregunta recodificada y le
    construye el mapa de opciones SÓLO con los renglones del CSV. Lo que se
    omita queda con `concept_option_id` NULL y vuelve al fallback del test
    anterior — o sea, el recode arregla seis códigos y deja el séptimo
    colisionando. Se exigen las opciones CON casos por la misma razón que allá:
    una opción vacía no produce renglón."""
    if not RECODES.exists():
        pytest.skip("sin recodes aprobados")
    loaded = {w for w, _ in hechos["qtype"]}
    declarado = defaultdict(set)
    for r in _rows(RECODES):
        if r["wave_id"] not in loaded:
            continue  # ola apagada por feature flag: el build la omite
        declarado[(r["concept_id"], r["wave_id"], r["q_id"])].add(int(r["option_id"]))

    faltantes = []
    for (cid, w, q), codes in sorted(declarado.items()):
        if cid not in hechos["members"]:
            faltantes.append((cid, w, q, "el concepto no existe en la BD"))
            continue
        if (w, q) not in hechos["members"][cid]:
            faltantes.append((cid, w, q, f"{w}/{q} no es miembro de {cid}"))
            continue
        omitidas = sorted(
            o
            for o in hechos["opts"].get((w, q), {})
            if o not in codes and hechos["casos"].get((w, q), {}).get(o, 0) > 0
        )
        if omitidas:
            faltantes.append(
                (cid, w, q, "códigos con casos sin declarar: "
                 + ", ".join(f"{o}={hechos['opts'][(w, q)][o]!r}" for o in omitidas))
            )
    assert not faltantes, (
        "recode NO exhaustivo: los códigos que faltan caen al fallback "
        "'{concept_id}:{código}' y pueden volver a colisionar.\n"
        + "\n".join(f"  {cid} ({w}/{q}): {msg}" for cid, w, q, msg in faltantes)
        + "\n  Arreglo: declara TODOS los códigos con casos de esa ola en "
        f"concept_recodes_approved.csv.\n  {REVISAR}"
    )


# ---------------------------------------------------------------------------
# 4. Un par `comparable` no puede tener una etiqueta que cambió de código
# ---------------------------------------------------------------------------


def test_ninguna_etiqueta_cambia_de_codigo_sin_recode(hechos):
    """En un par `comparable` categórico, la misma respuesta no puede vivir en
    códigos distintos en las dos olas sin un recode que lo declare.

    Es la firma mecánica de una **reasignación de códigos**, el caso que el
    catálogo canónico NO resuelve solo: si "NO HAY" es el 3 en 2021 y "No hay"
    el 2 en 2022, la unión crea dos renglones distintos y la serie se parte en
    dos mitades que parecen dos respuestas diferentes. Peor cuando el código
    liberado se reutiliza (el 3 de 2021 era "Covid-19" y el de 2025 es "problema
    de salud mental").

    Se ignoran tres cosas: los centinelas (el build ya los normaliza a
    7777/8888/9999, así que el 8="NS" de 2021 y el 8888="No sabe" de 2022 SÍ se
    alinean), las etiquetas "Otro"/"Ninguno" (casi toda ola arrastra varias con
    códigos distintos) y los códigos sin casos (una opción vacía no puede
    desplazar a ningún respondiente)."""
    desplazadas = []
    for r in _rows(EQUIV):
        if r["decision"] != "comparable" or r["ctype"] != "categorica":
            continue
        a, b = (r["wave_a"], r["q_a"]), (r["wave_b"], r["q_b"])
        if a not in hechos["qtype"] or b not in hechos["qtype"]:
            continue  # ola aún no cargada: el build también la ignora
        cid = hechos["qconcept"].get(a)
        recodes = {
            (row["concept_id"], row["wave_id"], row["q_id"]) for row in _rows(RECODES)
        } if RECODES.exists() else set()
        if cid and ((cid, *a) in recodes or (cid, *b) in recodes):
            continue  # el recode declara el desplazamiento a propósito
        etiq_b = {}
        for o, lbl in hechos["opts"].get(b, {}).items():
            k = _norm(lbl)
            if k and not OTRO_RE.match(k) and not _es_centinela(o, lbl):
                etiq_b.setdefault(k, o)
        for o, lbl in hechos["opts"].get(a, {}).items():
            k = _norm(lbl)
            if not k or OTRO_RE.match(k) or _es_centinela(o, lbl):
                continue
            if not hechos["casos"].get(a, {}).get(o, 0):
                continue
            o_b = etiq_b.get(k)
            if o_b is not None and o_b != o:
                desplazadas.append((a, b, lbl[:50], o, o_b, cid))
    assert not desplazadas, (
        "una respuesta vive en códigos distintos en las dos olas y no hay recode: "
        "la vista Año la partirá en dos renglones (y el código que quedó libre puede "
        "estar reutilizado por otra respuesta).\n"
        + "\n".join(
            f"  {wa}/{qa} ↔ {wb}/{qb}: {lbl!r} está en el código {oa} y en el {ob} "
            f"(concepto {cid})"
            for (wa, qa), (wb, qb), lbl, oa, ob, cid in desplazadas
        )
        + "\n  Arreglo: declara el recode en concept_recodes_approved.csv (exhaustivo "
        "para la ola que se mueve), o marca el par 'exclude' si la reasignación hace "
        f"la comparación imposible.\n  {REVISAR}"
    )


# ---------------------------------------------------------------------------
# 5. Centinelas dentro del promedio de las escalas (BUG CONOCIDO)
# ---------------------------------------------------------------------------


# Bug ARREGLADO el 2026-09-06 en el motor: `is_sentinel_label`
# descarta el valor cuando la ola guardó la escala como `categorica` y la
# ETIQUETA de la opción es centinela, y `_NUM_SENT_SUSPECT` cubre 99998/99999.
# Corrigió 19 celdas en 13 conceptos (la peor, 2022 p92_3: 198.65 -> 7.96).
# Este test era `xfail(strict=True)` para forzar justo esto: al arreglarse, el
# XPASS rompió la suite y obligó a quitar el marcador. Ahora es un guard vivo.
def test_promedio_por_anio_sin_centinelas(hechos):
    """El promedio de la vista Año no debe incluir los códigos "No sabe"/"No
    contesta" de las olas que guardaron la escala como categórica.

    En un concepto `numerica`, `_year_comparison` toma el `option_id` de esas
    olas COMO VALOR. La escala llega hasta 10, pero el código de "No sabe" es
    888 (2022) o 98 (2021): un 20% de no-sabe multiplica la media por 20. El
    resultado no se ve raro en la tabla — es un número, con su base ponderada —
    y ya afecta series publicadas de 2021 a 2025.

    Compara, para cada concepto `numerica` con algún miembro `categorica`, el
    "Promedio (media)" que devuelve el motor contra el mismo promedio ponderado
    recalculado sin las opciones cuya ETIQUETA es centinela."""
    from services.query.models import QueryRequest
    from services.query.runner import run_query

    afectados = []
    for cid, ms in sorted(hechos["members"].items()):
        if hechos["concepts"][cid] != "numerica":
            continue
        if not any(hechos["qtype"][m] == "categorica" for m in ms):
            continue
        ms = sorted(ms)
        res = run_query(
            QueryRequest(question_id=ms[-1][1], group_by="year", wave_id=ms[-1][0])
        )
        anios = res["counts"]["columns"][1:]
        prom = next(r for r in res["counts"]["rows"] if r[0] == "Promedio (media)")
        qid_por_anio = dict(ms)
        for i, anio in enumerate(anios):
            motor = prom[i + 1]
            if motor == "":
                continue
            sub = run_query(
                QueryRequest(
                    question_id=qid_por_anio[anio], group_by="answer", wave_id=anio
                )
            )
            es_num = sub["question"]["q_type"] == "numerica"
            num = den = 0.0
            for r in sub["rows"]:
                valor, etiqueta, cnt = (
                    (r[0], None, r[1]) if es_num else (r[0], r[1], r[2])
                )
                if valor is None or not cnt or valor in YEAR_SENTINELS:
                    continue
                if etiqueta is not None and _es_centinela(int(valor), etiqueta):
                    continue
                num += float(valor) * cnt
                den += cnt
            limpio = round(num / den, 2) if den else None
            if limpio is not None and abs(float(motor) - limpio) > 0.01:
                afectados.append((cid, anio, qid_por_anio[anio], motor, limpio))

    assert not afectados, (
        "el 'Promedio (media)' de la vista Año incluye códigos centinela "
        "(concepto, año, pregunta, media del motor, media sin centinelas):\n"
        + "\n".join(
            f"  {cid} {anio} {qid}: {motor} → debería ser {limpio}"
            for cid, anio, qid, motor, limpio in afectados
        )
        + "\n  Arreglo: backend/main.py — ver el `reason` del marcador xfail."
    )


# ---------------------------------------------------------------------------
# 6. Conceptos NOMINALES declarados `numerica` (declaración por arreglar)
# ---------------------------------------------------------------------------


def test_conceptos_numericos_son_escalas_no_nominales(hechos):
    """Un concepto `numerica` tiene que medir una cantidad o una escala.

    El "Promedio (media)" de la vista Año se calcula sobre el `option_id` de las
    olas categóricas. Si esos códigos son etiquetas nominales ("Trabajo",
    "Escuela", "Compras"), la media es la media de un número de catálogo: no
    significa nada y no hay forma de que el lector lo note. El criterio: se
    tolera una binaria (0/1, cuya media es una proporción legítima) y las
    escalas numeradas; se rechaza un catálogo de tres o más etiquetas de texto.
    """
    nominales = []
    for cid, ms in sorted(hechos["members"].items()):
        if hechos["concepts"][cid] != "numerica":
            continue
        for w, q in sorted(ms):
            if hechos["qtype"][(w, q)] != "categorica":
                continue
            sustantivas = [
                lbl
                for o, lbl in hechos["opts"].get((w, q), {}).items()
                if o not in YEAR_SENTINELS and not _es_centinela(o, lbl)
            ]
            texto = [lbl for lbl in sustantivas if not lbl.strip().replace(".", "").isdigit()]
            if len(sustantivas) >= 3 and len(texto) == len(sustantivas):
                nominales.append((cid, w, q, len(sustantivas), texto[:3]))
                break
    assert not nominales, (
        "concepto declarado 'numerica' cuyas opciones son nominales: el "
        "'Promedio (media)' de la vista Año no significa nada.\n"
        + "\n".join(
            f"  {cid} ({w}/{q}): {n} categorías de texto, p. ej. {ej}"
            for cid, w, q, n, ej in nominales
        )
        + "\n  Arreglo: ctype=categorica en el renglón de concept_equivalences.csv "
        f"(o 'exclude' si no son comparables).\n  {REVISAR}"
    )


# ---------------------------------------------------------------------------
# 7. Un `concept_id` fijado tiene que sobrevivir al encadenamiento
# ---------------------------------------------------------------------------


def test_todo_concept_id_fijado_llega_a_la_bd(hechos):
    """Si un renglón fija `concept_id`, las dos preguntas de ese renglón tienen
    que quedar en un concepto que se llame así.

    `load_concepts` guarda el pin como `pinned[find(a)]` **después** de `union`,
    o sea contra el root del momento; y `union(a,b)` muda el root al lado B. Al
    final sólo se consulta el root definitivo, así que un pin sobrevive
    únicamente si está en el ÚLTIMO renglón que toca el grupo. Basta con que
    alguien encadene el concepto con una ola más nueva y no repita el pin para
    que el id se recalcule en silencio (`attr_servicio_salud_donde_se_atendio`
    → `c2023_p80`): el build no falla, la vista Año sigue saliendo, y lo único
    que se rompe son los renglones de `concept_recodes_approved.csv` que
    apuntaban al nombre viejo.

    Se ignoran los renglones cuya ola aún no está cargada — el build también los
    ignora. La convención vigente (docs/crosswalk/README.md) es fijar el id sólo
    para las variables de cruce `attr_*` y repetirlo en TODOS los renglones de la
    cadena."""
    perdidos = []
    for r in _rows(EQUIV):
        pin = (r.get("concept_id") or "").strip()
        if r["decision"] != "comparable" or not pin:
            continue
        a, b = (r["wave_a"], r["q_a"]), (r["wave_b"], r["q_b"])
        if a not in hechos["qtype"] or b not in hechos["qtype"]:
            continue  # ola aún no cargada
        for nodo in (a, b):
            real = hechos["qconcept"].get(nodo)
            if real != pin:
                perdidos.append((a, b, nodo, pin, real))
    assert not perdidos, (
        "un `concept_id` fijado en concept_equivalences.csv NO llegó a la BD: el "
        "encadenamiento mudó el root y el id se derivó de la ola más nueva. Los "
        "recodes que apunten al nombre fijado quedan huérfanos.\n"
        + "\n".join(
            f"  {wa}/{qa} ↔ {wb}/{qb}: {w}/{q} quedó en {real!r} y no en {pin!r}"
            for (wa, qa), (wb, qb), (w, q), pin, real in perdidos
        )
        + "\n  Arreglo: repite `concept_id` en TODOS los renglones de esa cadena "
        "(un pin sólo sobrevive si está en el último renglón que toca el grupo), o "
        f"quítalo de todos y reapunta los recodes al id derivado.\n  {REVISAR}"
    )


# ---------------------------------------------------------------------------
# 8. Un par `exclude` no puede acabar en el mismo concepto por transitividad
# ---------------------------------------------------------------------------


def test_ningun_par_excluido_quedo_en_el_mismo_concepto(hechos):
    """Declarar `exclude` es decir "estas dos preguntas NO se comparan". Si la
    cadena las reúne igual, la declaración quedó anulada sin avisar.

    `exclude` no crea concepto, pero tampoco impide nada: el union-find sólo mira
    los renglones `comparable`, así que un camino indirecto
    (A↔C `comparable`, C↔B `comparable`) mete a A y B en el mismo concepto aunque
    A↔B esté excluido. El resultado es el peor de los dos mundos: la comparación
    prohibida se publica y encima queda un renglón en el CSV que asegura por
    escrito que no ocurre. El build lo lista como aviso, pero el build nunca
    falla.

    Es la contraparte de los 23 `exclude` del eslabón 2022↔2023, varios de los
    cuales son trampas posicionales con los códigos idénticos en las dos olas
    (`2022 p36_8 ↔ 2023 p38_8`, `2022 p31_5 ↔ 2023 p27_5`): ahí el `exclude` es la
    ÚNICA defensa, porque ni el detector de códigos divergentes ni la vista Año
    ven nada raro."""
    fundidos = []
    for r in _rows(EQUIV):
        if r["decision"] != "exclude":
            continue
        a, b = (r["wave_a"], r["q_a"]), (r["wave_b"], r["q_b"])
        if a not in hechos["qtype"] or b not in hechos["qtype"]:
            continue  # ola aún no cargada
        ca, cb = hechos["qconcept"].get(a), hechos["qconcept"].get(b)
        if ca is not None and ca == cb:
            fundidos.append((a, b, ca))
    assert not fundidos, (
        "par declarado 'exclude' que terminó en el MISMO concepto por "
        "transitividad: la exclusión no surtió efecto y la vista Año publica la "
        "comparación que el renglón dice prohibir.\n"
        + "\n".join(
            f"  {wa}/{qa} ↔ {wb}/{qb} conviven en {cid}"
            for (wa, qa), (wb, qb), cid in fundidos
        )
        + "\n  Arreglo: busca el camino indirecto que los une (algún par "
        "`comparable` intermedio) y córtalo, o acepta la fusión y borra el "
        f"renglón `exclude`, que hoy miente.\n  {REVISAR}"
    )


# ---------------------------------------------------------------------------
# 9. Un recode que MUEVE un código tiene que cubrir a todas las olas que lo usan
# ---------------------------------------------------------------------------


def test_recode_que_mueve_un_codigo_cubre_a_las_olas_que_lo_comparten(hechos):
    """Si un recode saca el código X de su lugar natural (`{concepto}:{X}`) es
    porque en ese concepto el X significa otra cosa. Entonces **ninguna otra ola
    del concepto puede seguir usando ese mismo X de forma nativa** para la misma
    respuesta: se quedaría con el canónico que el recode acaba de desocupar.

    Es el modo de falla más caro de esta capa y **no genera ningún aviso del
    build**, porque el detector de "códigos divergentes" compara *el par*, no *el
    concepto*, y sólo lista códigos que una ola tiene y la otra no. Cuando las
    dos olas tienen el mismo código con distinto significado, el par pasa limpio.

    El caso real que motivó el test (eslabón 2023↔2024): `2024 p117` ya estaba
    recodificado con `9 → c2025_p128:10` porque el `9` de **2025** es `Podcasts`.
    Al declarar `2023 p112 ↔ 2024 p117`, el concepto absorbió a 2021, 2022 y 2023
    —que usan el `9` para `No se entera`— y las tres quedaron nativas: la vista
    Año publicaba **Podcasts 0.8 / 0.2 / 0.5 %** en 2021-2023, una serie de una
    categoría que sólo existe desde 2025, y dejaba `No se entera` en blanco esos
    tres años. Lo mismo pasó con `c2025_p110` (el `Ninguno` de 2023 bajo
    `Sobre población de taxis`) y con `c2025_p127` (el `Todas las anteriores` de
    2023 bajo `Falta de vigilancia`, un par que no produce **ni un** aviso porque
    los dos catálogos tienen exactamente el mismo conjunto de códigos).

    Sobre el umbral de parecido: se compara la etiqueta de la ola recodificada
    contra la de la ola nativa con `difflib`, y se exige **0.85**. Los dos datos
    que lo enmarcan, medidos sobre esta BD: `'Todas las anteriores'` contra
    `'Todos los anteriores'` da **0.90** y hay que atraparlo; `'Servicios Médicos
    UANL'` contra `'Servicio Médico Naval'` da **0.837** y NO hay que atraparlo
    (son dos instituciones distintas que se parecen como cadenas). A diferencia
    del test 4, aquí **no** se ignoran las etiquetas `Otro`/`Ninguno`: la
    comparación es código a código entre dos olas, no dentro de una misma ola,
    así que un `Ninguno` que coincide en el mismo código es justo la señal que se
    busca —y es la que delató a `c2025_p110`—.
    """
    import difflib

    recodes = defaultdict(dict)
    for row in _rows(RECODES):
        recodes[(row["concept_id"], row["wave_id"], row["q_id"])][
            int(row["option_id"])
        ] = row["concept_option_id"]

    cruzadas = []
    for cid, ms in hechos["members"].items():
        if hechos["concepts"].get(cid) != "categorica":
            continue
        nativas = [m for m in ms if (cid, *m) not in recodes]
        for (w, q), mapa in ((k[1:], v) for k, v in recodes.items() if k[0] == cid):
            for code, coid in mapa.items():
                # Sólo interesan los códigos que el recode MUEVE: si va a su
                # lugar natural, no desocupa nada.
                if code in YEAR_SENTINELS or coid == f"{cid}:{code}":
                    continue
                etiq_mov = _norm(hechos["opts"].get((w, q), {}).get(code, ""))
                if not etiq_mov:
                    continue
                for nw, nq in nativas:
                    if code not in hechos["opts"].get((nw, nq), {}):
                        continue
                    if not hechos["casos"].get((nw, nq), {}).get(code, 0):
                        continue  # sin casos no desplaza a ningún respondiente
                    etiq_nat = _norm(hechos["opts"][(nw, nq)][code])
                    if not etiq_nat:
                        continue
                    if difflib.SequenceMatcher(None, etiq_mov, etiq_nat).ratio() >= 0.85:
                        cruzadas.append(
                            (cid, code, (w, q), etiq_mov, coid, (nw, nq), etiq_nat)
                        )
    assert not cruzadas, (
        "una ola quedó NATIVA con un código que otra ola del mismo concepto tuvo "
        "que mover con un recode: sus respuestas se publican bajo la etiqueta que "
        "el recode desocupó, y el build NO avisa de esto.\n"
        + "\n".join(
            f"  {cid} código {code}: {wm}/{qm} lo mueve a {coid} ({em!r}), pero "
            f"{wn}/{qn} sigue nativa con {en!r}"
            for cid, code, (wm, qm), em, coid, (wn, qn), en in cruzadas
        )
        + "\n  Arreglo: escribe el recode (exhaustivo) también para la ola nativa, "
        "mandando ese código al mismo canónico que el recode existente.\n"
        f"  {REVISAR}"
    )


# ---------------------------------------------------------------------------
# 11. Todo par `exclude` lleva `note`
# ---------------------------------------------------------------------------


def test_todo_par_excluido_tiene_nota():
    """Un `exclude` mudo es indistinguible de un renglón puesto por error.

    `exclude` no es una ausencia: es una **afirmación** —"estas dos preguntas no
    se comparan"— y es la única de las dos decisiones que el resto del sistema
    no puede verificar sola. Un `comparable` equivocado deja huella (avisos del
    build, catálogo cruzado, los tests de arriba); un `exclude` equivocado sólo
    deja un hueco en la vista Año, que se lee igual que "esa ola no preguntó".
    Sin la razón escrita, el siguiente eslabón no puede distinguir entre "ya se
    estudió y no es comparable" y "nadie lo miró", y acaba re-investigando o —
    peor— revirtiéndolo sin la evidencia que lo motivó.

    Ha pasado: el eslabón 2024↔2025 revirtió `p84↔p95` y `p85↔p96` (dos series
    limpias de cinco olas que estaban truncadas por un `exclude` **sin nota**) y
    tuvo que reconstruir desde cero por qué se habían excluido. Los ocho que
    quedaban sin nota se escribieron en el proceso 3 de ese mismo eslabón.

    El test es de FORMATO, no de criterio: no juzga la decisión, sólo exige que
    esté escrita."""
    mudos = [
        (r["wave_a"], r["q_a"], r["wave_b"], r["q_b"])
        for r in _rows(EQUIV)
        if r["decision"] == "exclude" and not (r.get("note") or "").strip()
    ]
    assert not mudos, (
        "hay pares `exclude` sin `note`: la decisión no se puede auditar ni "
        "heredar, y el hueco que deja en la vista Año se lee como si la ola no "
        "hubiera preguntado.\n"
        + "\n".join(f"  {wa}/{qa} ↔ {wb}/{qb}" for wa, qa, wb, qb in mudos)
        + "\n  Arreglo: escribe en `note` qué cambió (universo, catálogo, unidad, "
        "referente) y la cifra que lo sostiene, re-medida ponderando por "
        "factor_cvnl sobre respondientes iniciales.\n"
        f"  {REVISAR}"
    )


# ---------------------------------------------------------------------------
# 12. La vista Año no debe publicar 0.0 % de una categoría que la ola no ofreció
# ---------------------------------------------------------------------------


# T2 ARREGLADO en services/query/year_comparison.py::_categorical_tables: el camino
# categórico ahora distingue "sin casos" de "sin la opción" con
# `canonical_option_by_wave_option` (contiene (ola, código) si y sólo si esa ola
# ofrecía la categoría). No ofrecida → blanco en LAS DOS tablas; ofrecida con cero
# casos → 0 y 0.0 honestos en las dos. Antes los conteos dejaban en blanco todo cero
# y los porcentajes escribían 0.0 en esa misma celda: 1,014 celdas en 93 conceptos
# decían "nadie la eligió" donde la verdad era "esa ola no la ofrecía".
# Este test era `xfail(strict=True)`; el XPASS obligó a quitar el marcador.
def test_la_vista_anio_no_publica_cero_de_una_categoria_inexistente(hechos):
    """En la vista Año categórica, una ola que **no ofreció** una categoría debe
    salir en blanco, no en `0.0 %`.

    Las dos tablas que devuelve `_year_comparison` se contradicen en la misma
    celda: la de conteos hace `concept_row.append(c if c else "")` (blanco) y la
    de porcentajes hace `prow.append(round(c * 100.0 / denom[w], 1) if denom[w]
    else "")`, que con `c = 0` da **0.0**. La vista Año muestra los porcentajes,
    así que el usuario lee "esa ola preguntó y nadie eligió esta respuesta"
    donde la verdad es "esa ola no tenía esta respuesta".

    No es cosmético y **este trabajo lo agravó**: darle id propio a la categoría
    que sólo existe en una ola es exactamente lo que corrige los cruces E1-E4, y
    cada id propio estrena un renglón que sale 0.0 en las demás olas. Ejemplos
    medidos en esta BD: `c2025_p109` publica "Las instalaciones están en mal
    estado" con **0.0 en 2021-2024** (categoría que sólo existe en 2025) y
    "Falta de insumos/medicamentos" con 0.0 en 2024 y 2025; `c2025_p11` publica
    "Se quedó a hacer quehaceres del hogar" —la respuesta más frecuente de
    2025, 29.8 %— con 0.0 en 2022, 2023 y 2024.

    Arreglo (una línea, en el camino categórico de `_year_comparison`): que el
    porcentaje herede el mismo criterio que el conteo, o mejor, que distinga
    "sin casos" de "sin la opción" consultando `opt_to_canon` — la opción
    canónica está en el mapa si y sólo si esa ola la ofreció.

    El test se salta las opciones que la ola SÍ ofrece y quedaron en cero: ésas
    son un 0.0 legítimo."""
    import db_runtime
    from services.query.models import QueryRequest
    from services.query.runner import run_query

    # (ola, pregunta) → opciones canónicas que ESA ola llegó a ofrecer.
    ofrecidas = defaultdict(set)
    c = db_runtime.get_conn()
    try:
        for w, q, coid in c.execute(
            "SELECT wave_id, question_id, concept_option_id FROM options "
            "WHERE concept_option_id IS NOT NULL"
        ).fetchall():
            ofrecidas[(w, q)].add(coid)
    finally:
        c.close()

    falsos = []
    for cid, ms in hechos["members"].items():
        if hechos["concepts"].get(cid) != "categorica":
            continue
        qid = {w: q for w, q in sorted(ms)}
        w_ultima, q_ultima = sorted(ms)[-1]
        res = run_query(
            QueryRequest(
                question_id=q_ultima, group_by="year", wave_id=w_ultima, initial_only=True
            )
        )
        anios = res["percentages"]["columns"][1:]
        mapa = res.get("year_option_map") or []
        filas = [r for r in res["percentages"]["rows"] if r[0] != "Total"]
        # La misma celda en la tabla de conteos. Un código que la ola SÍ tiene
        # pero que no llegó al catálogo (`options`) aflora como 'Código N' y no
        # está en `ofrecidas`; su conteo, en cambio, sí trae casos. Mirar las dos
        # tablas evita contarlo como falso cero: el defecto es la celda sin
        # conteo que aun así publica 0.0.
        conteos = [r for r in res["counts"]["rows"] if r[0] != "Total"]
        for i, fila in enumerate(filas):
            if i >= len(mapa):
                break
            coid = f"{cid}:{mapa[i]['id_respuesta']}"
            for j, w in enumerate(anios, start=1):
                if fila[j] != 0.0:
                    continue
                if i < len(conteos) and conteos[i][j] not in ("", 0, None):
                    continue
                if coid not in ofrecidas.get((w, qid[w]), set()):
                    falsos.append((cid, mapa[i]["label"][:40], w))
    assert not falsos, (
        f"{len(falsos)} celdas de la vista Año publican 0.0 % de una categoría que "
        f"esa ola NO ofreció, en {len({f[0] for f in falsos})} conceptos. La tabla "
        "de conteos deja esas mismas celdas en blanco: las dos mitades de la misma "
        "respuesta se contradicen.\n"
        + "\n".join(
            f"  {cid}: {lbl!r} sale 0.0 en {w}" for cid, lbl, w in falsos[:15]
        )
        + (f"\n  … y {len(falsos) - 15} más" if len(falsos) > 15 else "")
        + "\n  Arreglo: en el camino categórico de _year_comparison, distinguir "
        "'sin casos' de 'sin la opción' (opt_to_canon ya lo sabe)."
    )


# ---------------------------------------------------------------------------
# 13. Ningún concepto publica la vista Año sobre una base marginal
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="DEFECTO DE DATOS conocido y sin dueño en esta capa: el módulo escolar "
    "(cp10-cp19) se guarda contra el respondent_id del ESTUDIANTE, así que con "
    "`initial_only=True` —el default de la app— la vista Año corre sobre 1-41 "
    "casos de los ~2,000 que contestaron: 12 conceptos, dos de ellos variables de "
    "cruce que la UI ofrece como filtro. Se arregla en la ETL hermana o en la UI, "
    "no en db/concepts/. Ver docs/crosswalk/README.md.",
)
def test_ningun_concepto_publica_la_vista_anio_sobre_una_base_marginal(hechos):
    """Si casi nadie de quien contestó una pregunta es respondiente inicial, la
    vista Año publica **ruido de muestreo con cara de serie**.

    `initial_only=True` es el default de la app y es lo correcto para casi todo:
    restringe a los respondientes iniciales y pondera con `factor_cvnl` para
    estimar población. Pero el módulo escolar se captura contra el
    `respondent_id` del **estudiante**, y casi ninguno es respondiente inicial:
    la pregunta tiene ~2,000 respuestas y la vista Año se calcula sobre 20-40.
    La app no muestra la n sin ponderar (la fila "Base (ponderada)" es la
    población estimada), así que nada avisa.

    Medido en esta BD: `c2025_cp15_1` publica **92.9 · 95.7 · 68.9** sobre
    32 · 41 · **23** casos, cuando la serie sobre los ~2,000 estudiantes es
    **81.7 · 90.4 · 89.1** — una caída de 27 puntos donde hay una de 1.3. Peor:
    `c2025_cp14` publica **51.3 · — · 0.0 · 14.4** sobre 39 · 0 · **1** · **2**
    casos, cuando la serie real es **62.0 · 43.5 · 54.1 · 56.7**: la app enseña
    un 0.0 % construido con **un solo respondiente**. Y `c2024_cp17_1` tiene
    **cero** respondientes iniciales en sus dos olas: su vista Año sale vacía.

    El umbral no es "n chica" —hay preguntas legítimamente raras con n=4 y ahí
    el n es toda la base— sino **n chica en proporción a quien sí contestó**: la
    pregunta se aplicó a mucha gente y el filtro por defecto se queda con una
    astilla. Se exige ≥25 % de la base propia cuando la pregunta tiene 100+
    respuestas. En esta BD el corte separa limpio: el percentil 5 de esa
    proporción está en 38 % y los 12 conceptos que caen debajo son los 12 del
    módulo escolar, dos de ellos variables de cruce (`attr_tipo_escuela`,
    `attr_nivel_actual_estudios`).

    Arreglo (no es de esta capa): que la ETL hermana ligue el módulo al
    respondiente inicial del hogar, o que la vista Año muestre la **n sin
    ponderar** junto a la base ponderada y se niegue a graficar por debajo de un
    mínimo."""
    import db_runtime

    c = db_runtime.get_conn()
    try:
        filas = c.execute(
            """
            SELECT q.concept_id, q.wave_id, q.q_id,
                   COUNT(DISTINCT CASE WHEN r.is_initial_respondent = 1
                                       THEN a.respondent_id END) AS ini,
                   COUNT(DISTINCT a.respondent_id) AS tot
            FROM questions q
            JOIN answers a ON a.wave_id = q.wave_id AND a.question_id = q.q_id
            JOIN responses r ON r.wave_id = a.wave_id
                            AND r.respondent_id = a.respondent_id
            WHERE q.concept_id IS NOT NULL
            GROUP BY 1, 2, 3
            """
        ).fetchall()
    finally:
        c.close()
    marginales = [
        (cid, w, q, ini, tot) for cid, w, q, ini, tot in filas
        if tot >= 100 and ini < 0.25 * tot
    ]
    assert not marginales, (
        "hay preguntas con concepto donde los respondientes iniciales son menos "
        "del 25 % de quien contestó: con el default de la app (`initial_only`), "
        "la vista Año publica esa celda sobre una astilla de la base y la fila "
        "'Base (ponderada)' no lo delata.\n"
        + "\n".join(
            f"  {cid} {w}/{q}: {ini} iniciales de {tot} que contestaron "
            f"({100.0 * ini / tot:.1f} %)"
            for cid, w, q, ini, tot in sorted(marginales)[:15]
        )
        + (f"\n  … y {len(marginales) - 15} más" if len(marginales) > 15 else "")
        + "\n  Arreglo: aguas arriba (la ETL debe ligar el módulo al respondiente "
        "inicial) o en la UI (mostrar la n sin ponderar y no graficar por debajo "
        "de un mínimo). NO se arregla en db/concepts/."
    )
