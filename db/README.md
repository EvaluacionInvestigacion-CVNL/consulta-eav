# Base de datos — esquema multi-año

Esta carpeta contiene el esquema y el constructor de la base de datos DuckDB.

## Archivos

| Archivo | Qué es |
|---|---|
| `schema.sql` | DDL del esquema multi-año (tablas, PKs). |
| `build_db.py` | Construye `data/encuesta_multianual.duckdb`: olas + overlays + conceptos. Único punto de entrada; no genera CSVs intermedios. |
| (los insumos por ola viven en `../data/waves/<año>/`, no aquí: son datos crudos, no código) |
| `overlays/*_approved.csv` | Correcciones **a mano** al catálogo crudo (etiquetas de opción faltantes, re-tipado de preguntas identificador). Ver [../docs/pipeline-datos.md](../docs/pipeline-datos.md). |
| `concepts/concept_equivalences.csv` | Equivalencias **a mano** de preguntas entre olas (habilitan la comparación por año). Ver [../docs/conceptos.md](../docs/conceptos.md). |
| `concepts/bootstrap_pairs.py` | Herramienta manual: redacta un borrador de equivalencias al agregar una ola. No es parte del build. |

## Modelo

Cada tabla de datos lleva `wave_id` (id de la ola/año) y forma parte de su clave
primaria. Esto permite tener varios levantamientos en el mismo archivo sin que se
mezclen: un mismo `respondent_id` o `q_id` puede existir en varias olas.

- **Optimizado para lectura / write-once**: no hay escrituras en vivo. El archivo
  se reconstruye entero con `build_db.py` y se recarga al servidor. `answers` se
  ordena físicamente por `(question_id, option_id)` para que DuckDB pode por
  zone-maps al filtrar por pregunta.
- **Armonización entre años**: `questions.concept_id` y `options.concept_option_id`
  enlazan cada pregunta/opción con su concepto canónico en `concepts` /
  `concept_options`. Los llena `build_db.py` a partir de
  `concepts/concept_equivalences.csv` (declarado a mano). Una pregunta con
  `concept_id` se puede consultar con `group_by="year"`.

## Reconstruir la BD

```bash
.venv/bin/python3 db/build_db.py
```

Escribe `data/encuesta_multianual.duckdb` cargando cada ola desde su fuente:

- **2025** — desde `data/waves/2025/encuesta.duckdb` (la BD original de una sola ola,
  **queda intacta**, READ_ONLY).
- **2024** y **2023** — desde `data/waves/<año>/*.csv`.

Valida unicidad de claves e integridad EAV por ola; aborta si algo no cuadra.
El backend (`config.py`), los tests (`conftest.py`) y el `DB_PATH` del servicio
en Render apuntan a `encuesta_multianual.duckdb`.

## De dónde salen los CSV de una ola (ETL)

Las olas que no vienen de la BD original 2025 se generan con el ETL
**`encuesta-asi-vamos-etl`** (repo hermano), que hace el reshape ancho→largo,
las variables derivadas y los atributos, y escribe `data/processed/<año>/*.csv`.
Esos 5 CSV se copian a `data/waves/<año>/` y `build_db.py` los carga.

Las olas en formato ancho (2016–2024) comparten un motor genérico
`src/transform/wave_wide.py` + un módulo de config por año
`src/config/survey_data_<año>.py` (mapeo de atributos, columnas roster, tipos,
nombres de derivadas). Para generar y cargar una ola:

```bash
# en el repo del ETL
.venv/bin/python3 run_etl.py --year 2023      # → data/processed/2023/*.csv
# luego, en este repo
cp ../encuesta-asi-vamos-etl/data/processed/2023/*.csv data/waves/2023/
.venv/bin/python3 db/build_db.py
```

## Agregar una ola futura (formato ancho)

1. En el ETL: crear `src/config/survey_data_<año>.py` (copiar el más parecido y
   ajustar nombres de columnas, roster, atributos y derivadas), registrarlo en
   `WIDE_WAVES` de `run_etl.py`, y correr `run_etl.py --year <año>`.
2. Copiar los 5 CSV a `data/waves/<año>/`.
3. En `build_db.py`: agregar `load_wave_csv(con, "<año>", <año>, "Encuesta <año>")`.
4. Correr `db/build_db.py` y luego los tests (`pytest`).

Cada ola trae su propio `factor_cvnl` (proyección poblacional de ese año); no se
combinan entre olas.

## Cómo consultar por año

`POST /api/query` acepta `wave_id` (opcional). Si se omite, usa la ola más
reciente. Ejemplo:

```json
{ "wave_id": "2025", "question_id": "p9_1", "group_by": "sexo" }
```

> **Comparar entre años** (una consulta que devuelva varias olas a la vez):
> `group_by="year"`, disponible para las preguntas que tienen `concept_id`.
> Ver [../docs/conceptos.md](../docs/conceptos.md).
