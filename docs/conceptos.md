# Conceptos — armonización entre años

La numeración de preguntas cambia entre olas (p. ej. "principal ocupación" es
`p3` en 2024 y `p1` en 2025) y algunas opciones se recodifican. Un **concepto**
agrupa las preguntas equivalentes a través de las olas, de modo que
`group_by="year"` pueda comparar la misma medida a lo largo del tiempo.

- `questions.concept_id` enlaza cada pregunta a su concepto.
- `concept_options (concept_option_id)` es el catálogo canónico de opciones;
  `options.concept_option_id` mapea la opción de cada ola a la canónica, para que
  códigos recodificados se alineen entre años.
- **Estado actual:** 311 conceptos (235 categóricos, 76 numéricos), 1,397 opciones
  canónicas, olas 2021–2025.

## Todo se declara a mano, en dos archivos

No hay emparejador automático ni CSVs generados: `db/build_db.py` construye la
capa de conceptos **en memoria** al construir la BD, leyendo sólo estos dos
insumos versionados.

### 1. `db/concepts/concept_equivalences.csv` — qué equivale a qué

```csv
wave_a,q_a,wave_b,q_b,ctype,decision,concept_id,source,note,reason
2024,cp2,2025,cp2,categorica,comparable,attr_sexo,manual,,
2022,p45_5,2023,p46_5,numerica,comparable,,frozen-auto,,
2024,p65,2025,p78,categorica,exclude,,manual,"rediseño: mismos códigos, otro significado",reactivo
```

Un renglón por **par** de preguntas equivalentes entre dos olas. Los pares se
encadenan de forma **transitiva** (2021↔2022, 2022↔2023, … → un concepto de
varias olas), así que agregar una ola nueva es agregar **renglones**, nunca tocar
código. Un par que referencia una ola aún no cargada se ignora hasta que exista.

| Columna | Qué hace |
|---|---|
| `ctype` | `numerica` \| `categorica`. Es el tipo del concepto: manda sobre el `q_type` de cada ola. Una escala 1..N guardada categórica en un año y numérica en otro se declara `numerica` (la vista Año la alinea por valor). |
| `decision` | `comparable` crea/extiende el concepto; `exclude` documenta un par que **no** debe compararse (rediseños, códigos reasignados). |
| `concept_id` | Opcional. Fija el id del concepto. Se usa para los `attr_*`, que `concept_recodes_approved.csv` referencia por nombre. Si va vacío, el id se deriva de la ola más reciente del concepto (`c2025_p9_1`) — estable, no se renumera al agregar preguntas. |
| `source` | `manual` = verificado por el equipo. `frozen-auto` = congelado del viejo emparejador difuso, **no verificado uno por uno**: es el candidato natural a auditar. |
| `note` | Nota **técnica** para el equipo (por qué se decidió así, con cifras). No se publica. |
| `reason` | Sólo en `exclude`, y obligatorio: el motivo **para el usuario**, de un vocabulario cerrado (`metadata.EXCLUSION_REASONS`: `base`, `opciones`, `reactivo`, `escala`, `unidades`, `captura`, `sin_datos`, `equipo`, `otra`). El build lo carga en `concept_exclusions` y la UI lo muestra bajo el resultado ("No comparable: cambió la escala de respuesta"). `sin_datos` (encabezados de batería sin respuestas) no se muestra. Un test falla si una exclusión no trae un motivo válido. |

### 2. `db/concepts/concept_recodes_approved.csv` — opciones recodificadas

```csv
concept_id,wave_id,q_id,option_id,concept_option_id
attr_sexo,2022,cp2_1,1,attr_sexo:0
attr_sexo,2022,cp2_1,2,attr_sexo:1
```

Sólo hace falta cuando una ola **recodificó los códigos** de una opción (sexo 1/2
en 2021-22 vs 0/1 en 2023-25) — algo que un par de preguntas no puede expresar.
Regla: una ola cubierta por un recode aporta **exactamente** las equivalencias
declaradas y nada más (por eso el código 3 "No binario" de 2021, que no está en
el recode, queda sin mapear en vez de inventar una opción canónica).

También sirve para el caso inverso: una opción **sin equivalente** en las demás
olas. Si el `concept_option_id` declarado no existe todavía en el catálogo pero la
ola sí tiene esa opción, entra al catálogo con su etiqueta real en vez de avisar.
Hace falta porque el motor, ante una opción sin mapeo, cae al fallback
`{concept_id}:{código}` y la fundiría con la opción que use ese **mismo código** en
otra ola aunque signifiquen cosas distintas. Por la regla de arriba el recode
debe ser **exhaustivo** para esa ola — lo que se omita cae en el fallback y vuelve
a colisionar.


## Cómo se construye (`db/build_db.py::load_concepts`)

1. **Encadenar** los pares `comparable` con union-find → grupos de preguntas.
2. Descartar los grupos de **una sola ola** (no hay nada que comparar).
3. **Id**: el `concept_id` fijado si lo hay; si no, `c<ola más reciente>_<q_id>`.
   **Etiqueta**: el texto de la pregunta en la ola más reciente (espacio en
   blanco colapsado; el `q_text` crudo trae saltos de línea).
4. **Catálogo canónico**, sólo para conceptos **categóricos** — los numéricos se
   alinean por VALOR en la vista Año, así que un catálogo no significa nada:
   la **unión** de las opciones de las olas miembro (gana la etiqueta de la ola
   más reciente), con los centinelas normalizados al código estándar del app
   (2021 codifica No sabe/No contesta como 8/9 → 8888/9999).
5. **Mapa de opciones**: identidad para las olas nativas, más los renglones
   declarados en los recodes.

### Avisos de integridad

El build no falla, pero **avisa** (y conviene revisar los avisos al agregar una ola):

- par declarado `comparable` cuyas opciones **no alinean por código** (lista sólo
  la diferencia: `sólo en 2024=[14, 15], sólo en 2025=[12]`). Suele ser una ola
  que agregó o quitó opciones — la unión lo maneja, pero vale confirmar que no es
  una **reasignación** de códigos (eso sería `exclude`);
- par `exclude` que terminó en el mismo concepto por **transitividad**;
- recode que apunta a un concepto inexistente, o a una opción canónica inexistente
  **que la ola tampoco tiene** (si la tiene, no es error: es una opción sin
  equivalente y se agrega al catálogo, ver arriba).

## Agregar una ola nueva

```bash
# 1. cargar la ola (ver pipeline-datos.md), luego redactar un borrador de pares
.venv/bin/python db/concepts/bootstrap_pairs.py --new 2026
# 2. revisar concept_equivalences.draft.csv, mover los renglones correctos a
#    concept_equivalences.csv (source=draft → source=manual)
# 3. reconstruir y correr tests
.venv/bin/python db/build_db.py
.venv/bin/pytest
```

`bootstrap_pairs.py` es una **herramienta manual, no parte del build**: propone
pares por similitud de texto (y por nombre de atributo, que sí es exacto) para no
partir de una hoja en blanco. Se equivoca — junta baterías distintas y separa
preguntas que sólo cambiaron de redacción — por eso escribe un borrador aparte
que nadie carga hasta revisarlo. Cada renglón trae `sim` para priorizar.

## Cómo lo consume el motor

`compare_across_waves()` en `backend/services/query/year_comparison.py`:
1. Resuelve el `concept_id` de la pregunta seleccionada.
2. Para cada ola miembro arma el SQL del camino plano (ponderado por el
   `factor_cvnl` de esa ola) y corre todas las olas en una sola consulta
   (`UNION ALL`).
3. Alinea las opciones por `concept_option_id` (no por código crudo), de modo que
   opciones recodificadas se comparen como la misma.
4. Traduce los filtros entre olas vía la opción canónica (un filtro de "mujeres"
   funciona en cualquier ola aunque el código de sexo cambie).
5. Numéricas → media ponderada por año, **alineadas por valor**; categóricas →
   distribución % por año.

**Transparencia del crudo por año.** La vista Año **no** incluye la columna
`id_respuesta` (el código canónico no es estable entre olas): las columnas son
`[Respuesta, ...años]`. El dato **real** de cada ola va en `year_option_map` —
por cada opción, `{año: {option_id, label}}`. La UI usa esto para marcar (con un
tooltip) las opciones cuya **etiqueta** varió entre años, mostrando los distintos
nombres que tuvo (p. ej. "Hombre / Masculino"). Así la comparación queda alineada
sin esconder que la respuesta se llamó distinto según el año. No va al CSV.

La bitácora del trabajo de armonización —qué se propuso, qué se verificó y qué
se descartó, eslabón por eslabón— vive en [crosswalk/](crosswalk/README.md).

Ver también: [arquitectura.md](arquitectura.md) ·
[pipeline-datos.md](pipeline-datos.md) · [desarrollo.md](desarrollo.md).
