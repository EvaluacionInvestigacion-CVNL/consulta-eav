# Arquitectura

Herramienta de consultas sobre la encuesta *Así Vamos*, olas 2021–2025.

## Panorama

```
┌──────────────────────┐        /api/*         ┌───────────────────────────┐
│  SPA Vue 3 + Vite     │  ───────────────────► │  FastAPI (Python)         │
│  Tailwind · Chart.js  │  ◄─────────────────── │  • motor de consultas     │
│  modo manual + IA     │     JSON / CSV        │  • builder SQL seguro     │
└──────────────────────┘                       │  • IA por tool-use (chat) │
                                                └─────────────┬─────────────┘
                                                              │ solo lectura
                                                     ┌────────▼────────┐
                                                     │  DuckDB (EAV)    │
                                                     │  multi-año       │
                                                     └─────────────────┘
```

En producción FastAPI **también** sirve la SPA compilada como archivos 
estáticos, así que todo es un solo servicio.

| Capa           | Tecnología                                          |
|----------------|-----------------------------------------------------|
| Base de datos  | DuckDB (embebida, solo lectura)                     |
| Backend        | Python · FastAPI · Pydantic · Uvicorn               |
| IA             | Google Gemini                                       |
| Frontend       | Vue 3 · Vite · Tailwind CSS v4                      |
| Gráficas       | Chart.js                                            |
| Tests          | pytest — 138 tests                                  |
| Deploy         | Render.com (dashboard; `render.yaml` es referencia) |

## Esquema de datos (EAV multi-año)

Cada tabla de datos lleva `wave_id` (año de la ola) como parte de la PK, así que
varias olas coexisten sin colisionar. Ver `db/schema.sql`.

```sql
waves                 (wave_id PK, year, label, n_respondents, notes)
answers               (wave_id, respondent_id, question_id, option_id, value)
options               (wave_id, question_id, option_id) PK, option_label, concept_option_id
questions             (wave_id, q_id) PK, q_text, q_section, q_type, q_notes, q_info, q_block, concept_id
respondent_attributes (wave_id, respondent_id, attribute) PK, question_id, value
responses             (wave_id, respondent_id) PK, is_initial_respondent, nombre, factor_cvnl, city_id
concepts              (concept_id PK, label, q_type)
concept_options       (concept_id, concept_option_id PK, label, sort_order)
```

Cada par `(respondiente, pregunta)` es un renglón en `answers`.
Una respuesta guarda **exactamente uno** de:
- `option_id` (código de la opción, para preguntas **categóricas**; `value` NULL), o
- `value` (número, para preguntas **numéricas**; `option_id` NULL).

La etiqueta legible de un `option_id` vive en `options`. Los filtros
demográficos viven en `respondent_attributes`, donde `attribute` es un nombre
amigable (`sexo`) keyeado a un `question_id` de la encuesta, y `value` es el
`option_id` cuya etiqueta está en `options`.

Un filtro puede ser un atributo (`{"attribute": "sexo", "value": 1}`, o
`city_id`) o **cualquier pregunta categórica** (`{"question": "p52", "value":
[1, 2]}`), que se resuelve con un JOIN sobre `answers`. Los atributos son, en el
fondo, preguntas con nombre amigable, así que entre olas las dos formas se
traducen igual (ver *Filtros entre olas* abajo).

### Por qué `answers` no tiene PK ni FK

Las dos ausencias son deliberadas y parecen errores si no se documentan — no las
"arregles" sin leer esto:

- **Sin PRIMARY KEY.** `option_id` es NULL en las preguntas numéricas, así que no
  puede formar parte de una PK. Además un índice ART sobre 1.1M+ renglones no
  ayuda a los scans/agregados que hace el motor (DuckDB es columnar y poda por
  zone-maps) y engorda el archivo. La unicidad de
  `(wave_id, respondent_id, question_id)` se valida en `build_db.py`, no en el
  esquema.
- **Sin FOREIGN KEY.** Existen ~76 referencias `(question_id, option_id)` sin
  fila correspondiente en `options`; el backend ya las maneja con `LEFT JOIN`.
  Una FK las rechazaría y el build fallaría.

`answers` además se ordena **físicamente** al cargar (ver `build_db.py`) para que
DuckDB pode por zone-maps al filtrar por pregunta.


## Organización del backend

`backend/main.py` sigue siendo el punto de entrada (`uvicorn main:app`), pero
sólo **arma la app**: middleware, routers y el mount del front. No define
endpoints ni lógica. Debajo hay tres capas:

```
routers/      → services/      → repositories/ → db_runtime
(HTTP)          (reglas+caché)   (SQL fijo)      (conexión)
```

- `routers/` — endpoints delgados, cero lógica: `catalog.py` (preguntas,
  atributos, ciudades, olas, recodes, presets), `query.py` (`/api/query` y la
  descarga CSV) y `health.py` (diagnóstico).
- `services/` — orquestación, reglas de negocio y **los `lru_cache`**:
  `catalog_service.py` (arma el catálogo, traduce presets entre olas),
  `wave_service.py` (resolución/validación de olas) y `ordering.py` (funciones
  puras de ordenamiento, no tocan la base).
- `repositories/` — **el único lugar donde vive texto SQL fijo**:
  `survey_repository.py` (olas, preguntas, opciones) y
  `responses_repository.py` (atributos demográficos, ciudades). Reciben un
  `conn` abierto y devuelven filas crudas; no cachean ni validan.
- `db_runtime.py` — dueño de la conexión DuckDB de solo lectura (`get_conn()`,
  usable con `with`).
- `config.py` carga `.env` y expone rutas de runtime como `DB_PATH` y
  `STATIC_DIR`.
- `csv_export.py` serializa el resultado del motor a CSV (`query_result_to_csv`)
  y normaliza las celdas vacías.
- `services/query/` **es** el motor, repartido por responsabilidad:
  `models.py` (`QueryRequest`), `runner.py` (`run_query` y las cuatro formas),
  `year_comparison.py` (la vista Año), `sql_builder.py` (los fragmentos de SQL
  que se componen), `sentinels.py` (qué códigos son No sabe/No contesta) y
  `pivot.py` (armado de las tablas y cubetas geográficas).
- `services/chat/` es el modo IA: `prompts.py` (el texto que se le da al
  modelo), `gemini.py` (lo único que sabe que el proveedor es Gemini),
  `query_tool.py` (la herramienta `query`, que llama al motor) y
  `conversation.py` (el ciclo de tool use). Sus endpoints están en
  `routers/chat.py` como los demás.

**Qué significa aquí “repositorio”.** Es *dónde vive el SQL*, no una costura
para intercambiar la persistencia: la base es un archivo de solo lectura
horneado en build, los tests corren contra datos reales a propósito y no hay
escrituras. Interfaces/ABCs o un método de repositorio por endpoint serían
ceremonia pura. Regla práctica: un servicio que sólo hace
`return repo.x(conn, wave)` sobra — que el router llame al repositorio.

`services/query/` es el único subsistema que **compone SQL en tiempo de
ejecución** (el builder seguro), así que sus consultas armadas no pasan por
`repositories/`, cuyas consultas son fijas y parametrizadas. Las consultas fijas
que el motor traía adentro —tipo de pregunta, miembros de un concepto, catálogos
de opciones, el barrido de centinelas— sí se movieron a repositorios.

Dos decisiones que conviene conocer antes de tocarlo:

- `runner` arma un `QueryContext` una sola vez (ola, pregunta, ponderación, SQL
  de filtros, exclusión de centinelas) y cada forma de salida lee de ahí. Por eso
  los armadores reciben un contexto y no diez parámetros sueltos.
- `year_comparison` recibe `_build_context` **como parámetro** en vez de
  importarlo: el motor llama a la vista Año y la vista Año reutiliza el motor, así
  que inyectarlo deja la dependencia en un solo sentido y a la vista. El SQL de la
  base y de la distribución vive en `QueryContext.base_sql()` y
  `QueryContext.distribution_sql()`: una sola definición para la forma plana y la
  vista Año.

Las dependencias van en **un solo sentido** —`routers`/`chat` → `services`
(incluido `services/query`) → `repositories` → `db_runtime`— así que no hay imports diferidos ni
orden de carga significativo: cualquier módulo se puede importar aislado.
**Nada re-exporta**: cada consumidor —los tests incluidos— importa del módulo
dueño del símbolo, así que `main` sólo contiene lo que de verdad es suyo (`app`).

## Motor de consultas (`backend/query_engine.py`)

Todo pasa por `run_query()` (`POST /api/query`). Según `group_by` y el tipo de
pregunta hay **cuatro formas** más la comparación entre años:

| `group_by`        | Categórica                          | Numérica                                   |
|-------------------|-------------------------------------|--------------------------------------------|
| `"answer"` (plana)| 1 renglón por opción: conteo + %    | distribución de frecuencias por valor + %  |
| ≠ `"answer"` (pivote) | 2 tablas (conteos + %) con Total | igual + fila **Promedio** (media ponderada)|
| `"year"`          | pivote entre olas, alineado por opción canónica | media ponderada por año         |

Helpers compartidos que arman el SQL y las tablas:

- **`_base_from_where(...)`** — bloque `FROM/JOIN/WHERE` común (answers ⋈
  responses de la misma ola + JOINs de filtros + WHERE de ola/pregunta/cohorte).
  Slots: `extra_where` (centinelas / no-nulos) y `with_options` (LEFT JOIN al
  catálogo de opciones).
- **`_group_expr_sql(group_by, wave)`** — expresión SQL de la etiqueta de columna
  del pivote (city_id / rangos de edad / recode / atributo).
- **`_city_buckets(city_filter)`** — buckets de columna al agrupar por ciudad.
- **`_collapse_city_cells(...)`** — colapsa city_ids crudos en los buckets de
  metadata (11 municipios AMM + 4 agregados).
- **`_pivot_count_pct_rows(...)`** — ensambla filas de conteos y porcentajes +
  fila Total (idéntico para numérica y categórica).

`compare_across_waves()` maneja `group_by="year"` en **una sola consulta**:
arma un `QueryContext` por ola (las mismas validaciones y el mismo SQL de la forma
plana, sin consultar la base) y junta la distribución y la base de todas las olas
con `UNION ALL`. Después alinea las opciones por `concept_option_id` en Python
(ver [conceptos.md](conceptos.md)). Los metadatos del concepto y el catálogo de
preguntas se leen una vez por proceso: la base no muta en runtime. Antes eran ~3
consultas por ola más 5 de metadatos, y cada viaje a DuckDB cuesta mucho con la
CPU de Render.

### Filtros entre olas (`services/dimension_service.py`)

Los filtros llegan en la codificación de la ola base y se reexpresan en cada ola:
el código baja a su `concept_option_id` y vuelve a subir en la pregunta
equivalente de la ola destino (la que respalda el atributo en esa ola, o el
miembro del mismo concepto si es un filtro por pregunta). Un `concept_option_id`
puede agrupar varios códigos de una ola (los "Otro"), y el filtro los trae
todos, también en la ola base.

La traducción es **estricta**: si un valor no tiene equivalente en alguna ola,
la consulta da 400 nombrando las olas que faltan. Antes se aplicaba el código
crudo, lo que filtraba otra categoría en silencio (`modo_transporte` 2025 no
tiene opciones canónicas). La edad viaja tal cual (es numérica) y `city_id`
también (los municipios no se recodifican).

Todo sale de tres catálogos cacheados (preguntas, opciones armonizadas y
atributo → pregunta por ola; ~15k filas), así que validar un filtro son
búsquedas en diccionarios, no consultas. `GET /api/dimensions` usa los mismos
catálogos para decirle a la UI qué atributos y preguntas cubren todas las olas
de la pregunta consultada.

## Decisiones de diseño

- **DuckDB embebida y de solo lectura.** Los datos son referencia fija, no
  transaccional. Columnar → escaneos agregados rápidos sobre 1.1M filas. Es
  **un archivo** que no se versiona: se reconstruye en el build a partir de los
  insumos versionados; cada conexión abre `read_only=True`.
- **SQL generado con validación por allowlist, no ORM.** Las consultas se
  componen dinámicamente. Cada identificador del usuario (`question_id`,
  `group_by`, cada `attribute` o `question` de filtro) se valida contra una allowlist
  derivada de la BD **antes** de construir cualquier string SQL; los valores son
  enteros coaccionados por Pydantic. SQL dinámico con superficie de
  inyección **cero**, y el SQL generado se devuelve al cliente (transparencia).
- **Proyección a población (`factor_cvnl`).** Con `initial_only=true` (default)
  se restringe a respondientes iniciales y se pondera por el factor de expansión
  de cada uno → estimaciones poblacionales. Con `false` se cuentan filas crudas.
- **Centinelas.** Los códigos `7777`/`8888`/`9999` (No aplica / No sabe / No
  contesta) son respuestas reales: se conservan en conteos y porcentajes, pero se
  **excluyen** de estadísticos numéricos (promedios). Además, la "regla de techo"
  detecta centinelas no estándar por pregunta numérica (ver
  `_extra_numeric_sentinels`): un código sospechoso (p. ej. 99, 999) sólo cuenta
  como centinela si **excede** el valor real máximo de esa pregunta. Esa regla
  filtra `q_type='numerica'`, así que no ve las escalas que una ola guardó como
  `categorica`; para ésas la vista Año descarta el valor cuando la **etiqueta**
  de la opción es centinela (`_is_sentinel_label`). El criterio es por etiqueta
  y **nunca por magnitud**: hay categorías sustantivas con código alto
  (`2024 p52_5` código 6666) que un filtro a ciegas borraría.
- **Modo IA por tool-use, no text-to-SQL.** El modelo no emite SQL: se le dan las
  **mismas** funciones de consulta que usa la UI y solo puede actuar
  invocándolas, así toda respuesta de IA corre por el mismo camino validado y
  ponderado. Superficie de inyección cero. Es opcional: sin `GEMINI_API_KEY` la
  app corre en modo manual.
- **Caché.** Los endpoints de metadata (`/api/questions`, `/api/attributes`,
  `/api/cities`) son inmutables durante la vida del proceso y se cachean con
  `lru_cache`.

## Endpoints

| Método | Ruta               | Descripción                             |
|--------|--------------------|-----------------------------------------|
| GET    | `/api/questions`   | Preguntas + opciones (por ola)          |
| GET    | `/api/attributes`  | Atributos de filtro + etiquetas         |
| GET    | `/api/cities`      | Municipios distintos                    |
| GET    | `/api/waves`       | Olas disponibles (marca la default)     |
| GET    | `/api/dimensions`  | Por qué se puede filtrar una pregunta (`mode=wave\|year`) |
| GET    | `/api/recodes`     | Definiciones de recode                  |
| GET    | `/api/presets`     | Recetas de análisis (group_by+filtros)  |
| POST   | `/api/query`       | Corre una consulta → JSON               |
| POST   | `/api/query/csv`   | Corre una consulta → descarga CSV       |
| POST   | `/api/chat`        | Consulta en lenguaje natural (modo IA)  |
| GET    | `/api/health`      | Health check                            |

Ver también: [pipeline-datos.md](pipeline-datos.md) ·
[conceptos.md](conceptos.md) · [desarrollo.md](desarrollo.md).
