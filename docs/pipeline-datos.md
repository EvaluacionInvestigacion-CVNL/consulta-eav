# Pipeline de datos

Cómo se construye `data/encuesta_multianual.duckdb`.

> Importante: **nunca se editan las fuentes crudas.** Toda corrección se hace
> con *overlays* declarativos (CSVs) que `build_db.py` aplica al construir. Así
> las correcciones quedan versionadas, auditables y reproducibles.

## Cómo está organizado `data/`

Dos carpetas, una por etapa del pipeline, ambas indexadas por año:

```
data/
├── source/<año>/     ← materia prima CRUDA (insumo del ETL externo)
│   ├── Cuestionario <año>.xlsx    instrumento: preguntas, códigos y etiquetas
│   └── EAV <año>.xlsx             exportación cruda del levantamiento
├── waves/<año>/      ← ya en esquema EAV (insumo de build_db.py)
│   ├── 2021-2024: los 5 CSV que produce el ETL
│   └── 2025: encuesta.duckdb (BD original de una ola, queda INTACTA)
└── encuesta_multianual.duckdb     ← SALIDA: la BD que lee la app
```

`source/` es **aguas arriba** de `waves/`: el ETL `encuesta-asi-vamos-etl` (repo
hermano) lee el cuestionario y el EAV de un año y escribe los 5 CSV de esa ola.
Este repo no corre ese ETL — sólo consume `waves/`. La única excepción es
`db/overlays/build_option_fixes.py`, que lee el cuestionario para recuperar
etiquetas de opción faltantes (Capa B, abajo).

> `source/2019/` existe pero **no hay** `waves/2019/`: la materia prima está
> guardada, la ola no está cargada. `source/2025/` no existe: esa ola no vino del
> ETL sino de la BD original.

## Fuentes por ola

| Ola  | Fuente que carga `build_db.py`         | Materia prima             |
|------|----------------------------------------|---------------------------|
| 2025 | `data/waves/2025/encuesta.duckdb`      | — (ya venía en EAV)       |
| 2024 | `data/waves/2024/*.csv`                | `data/source/2024/*.xlsx` |
| 2023 | `data/waves/2023/*.csv`                | `data/source/2023/*.xlsx` |
| 2022 | `data/waves/2022/*.csv`                | `data/source/2022/*.xlsx` |
| 2021 | `data/waves/2021/*.csv`                | `data/source/2021/*.xlsx` |

Cada ola aporta 5 CSVs (`responses`, `questions`, `options`,
`respondent_attributes`, `answers`), producidos por el ETL externo que convierte
el formato ancho del cuestionario a largo (EAV). Ver `db/README.md`.

## `db/build_db.py`

Idempotente: **borra y reconstruye** la BD desde cero en cada corrida
(write-once). Pasos:

1. **`_run_schema`** — ejecuta `db/schema.sql` (DDL multi-año).
2. **`load_wave_2025`** — `ATTACH` de la BD original (solo lectura) e inserta la
   ola 2025 con su `wave_id`. La original nunca se modifica.
3. **`load_wave_csv`** × 2024/2023/2022/2021 — inserta cada ola desde sus CSVs.
4. **`apply_question_fixes`** — overlay de reparación de `questions` (ver abajo).
5. **`apply_option_fixes`** — overlay Capa B (ver abajo).
6. **`apply_question_type_fixes`** — overlay de re-tipado (ver abajo).
7. **`load_concepts`** — arma la capa de conceptos EN MEMORIA desde
   `db/concepts/concept_equivalences.csv` (ver [conceptos.md](conceptos.md)).
   No lee ni escribe CSVs generados.
8. **`_validate`** — chequeos de integridad.


```bash
.venv/bin/python db/build_db.py
```

## Overlays de corrección

### Capa A — no es overlay, es del motor
El camino categórico usa `LEFT JOIN options`: las respuestas cuyo
`option_id` no está en el catálogo **igual se cuentan** (como
`"Código N"`). Si fuera `INNER JOIN`, esas respuestas se caerían, la base se
encogería y todos los porcentajes se inflarían. Vive en `backend/query_engine.py`, no en
el build. Hay tests de regresión (`test_flat_categorical_base_equals_raw_total`).

### Reparación del catálogo de preguntas
**Archivo:** `db/overlays/question_fixes_approved.csv`
**Función:** `apply_question_fixes(con)`

El ETL de 2024 dejó **19 `q_id` que aparecen en `answers` pero no tienen renglón
en `questions`**: 68,327 respuestas invisibles para la app y para la capa de
conceptos. La causa está en el instrumento — la columna *Código* del
`Cuestionario 2024.xlsx` viene **vacía** en esos reactivos —, y el ETL reaccionó
de dos maneras: o escribió el catálogo bajo un nombre y las respuestas bajo otro
(`p1081` contra `p108_1`, `p139_P` contra `p139`, `p55` contra `p55_1`), o no
escribió el renglón en absoluto (`p7_1`, `p61_2`, `p8_2`).

Esto no es sólo una pregunta que falta en el selector: **un par de
`concept_equivalences.csv` que nombre un `q_id` sin renglón se ignora en
silencio** —no falla, no crea concepto, no avisa— y uno que apunte al renglón
vacío publica una columna en blanco en la vista Año.

Tres acciones, aplicadas en ese orden:

| acción | qué hace |
|---|---|
| `drop` | borra las respuestas de un `q_id` (duplicados exactos del ETL) |
| `rename` | unifica bajo un solo nombre las dos mitades de una pregunta partida; toca `questions`, `options`, `answers` y `respondent_attributes` |
| `insert` | da de alta la pregunta que no tiene ninguna mitad |

```csv
wave_id,action,question_id,target,q_text,q_section,q_type,reason
2024,rename,p1081,p108_1,,,,"typo del ETL: falta el guion bajo"
2024,insert,p7_1,,P 7 1 Vacaciones,economia_y_trabajo,categorica,"..."
```

Como el nombre destino nunca existe en la tabla que se renombra, un choque de PK
sería un error de declaración y **revienta el build**.

Al final, toda pregunta del overlay que quede `numerica` y traiga su dato en
`answers.option_id` se **migra a `answers.value`** — el espejo de lo que hace el
re-tipado de abajo en la dirección contraria. Eran cuatro (`p8_2`, `p9_2`,
`p20_1`, `p20_2`: minutos y horas que el ETL cargó como si fueran códigos de
opción, 11,442 respuestas).

Las etiquetas que le falten a una pregunta dada de alta aquí van, como
cualquier otra, en `options_fixes_approved.csv`.

`tests/test_db_freshness.py::test_sin_q_id_huerfanos_en_2024` es el guard: falla
si vuelve a aparecer un `q_id` huérfano en esa ola.

### Capa B — reparación del catálogo de opciones
**Archivo:** `db/overlays/options_fixes_approved.csv`
**Función:** `apply_option_fixes(con)`

Las fuentes crudas a veces no traen etiqueta para códigos que sí aparecen en
`answers` (huecos de catálogo). Este overlay, revisado contra el cuestionario
original, agrega/corrige esas etiquetas. Si
`(wave, question, option)` existe se **reemplaza** la etiqueta; si no, se
**inserta**.

```csv
wave_id,question_id,option_id,option_label
2021,p128,1,"Muy de acuerdo"
```

### Re-tipado de preguntas identificador
**Archivo:** `db/overlays/question_type_fixes_approved.csv`
**Función:** `apply_question_type_fixes(con)`

Algunas preguntas vienen como `numerica` en la fuente pero son en realidad
**identificadores codificados** (colonia de destino, ruta de camión): sus valores
son códigos, no cantidades, así que promediarlos no tiene sentido.
Este overlay corrige `q_type` para que el motor las trate como categóricas.

Como venían tipadas numéricas, sus respuestas se cargaron en `answers.value`
(con `option_id` NULL); el motor categórico agrupa por `option_id`, así que la
función **también migra** el código `value → option_id` para esas preguntas.

```csv
wave_id,question_id,q_type,reason
2022,p13,categorica,"colonia de destino (identificador codificado, no numerico)"
```

## Validación (`_validate`)

Por cada ola verifica, y **aborta el build** si algo falla:
- **Unicidad** de `(respondent_id, question_id)` en `answers`.
- **Integridad EAV**: exactamente uno de `(option_id, value)` no nulo.
- Reporta `responses`, `answers`, duplicados y filas EAV malformadas por ola.

## Cómo agregar una ola nueva

1. Correr el ETL externo para producir `data/waves/<año>/*.csv`.
2. Agregar una línea `load_wave_csv(con, "<año>", <year>, "Encuesta <año>")` en
   `main()` de `build_db.py`.
3. (Opcional) Agregar los pares de equivalencia de la ola nueva a
   `db/concepts/concept_equivalences.csv` para incluirla en las comparaciones
   entre años — ver [conceptos.md](conceptos.md).
4. Reconstruir: `.venv/bin/python db/build_db.py`.
5. Correr tests: `.venv/bin/pytest`.
6. Commitear los insumos (CSVs de la ola, `build_db.py`, CSVs de conceptos), nunca
   el `.duckdb`: Render reconstruye la BD en su build (ver [desarrollo.md](desarrollo.md)).

Ver también: [arquitectura.md](arquitectura.md) · [conceptos.md](conceptos.md)
· [desarrollo.md](desarrollo.md).
