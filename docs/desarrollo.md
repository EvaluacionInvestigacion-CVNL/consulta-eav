# Desarrollo

## Requisitos

- Python 3.12+ (el repo usa un venv en `.venv/`)
- Node 18+ (para el frontend)

## Setup

```bash
# Backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # requirements.txt + pytest, httpx, ruff

# Frontend
cd frontend && npm install
```

## Correr localmente

```bash
# Backend (FastAPI) — API en :8000
cd backend
../.venv/bin/uvicorn main:app --port 8000 --reload

# Frontend (Vite dev server, proxea /api → :8000)
cd frontend
npm run dev        # http://localhost:3000
```

El modo IA es opcional:

```bash
export GEMINI_API_KEY=key   # sin esto, la app corre en modo manual
```

## Variables de entorno

| Variable         | Default                              | Uso                                         |
| ---------------- | ------------------------------------ | ------------------------------------------- |
| `DB_PATH`        | `../data/encuesta_multianual.duckdb` | Ruta a la BD DuckDB                         |
| `STATIC_DIR`     | `../frontend/dist`                   | SPA compilada                               |
| `GEMINI_API_KEY` | — (sin default)                      | Habilita el modo IA                         |
| `FEATURES`       | — (vacío: todo apagado)              | Feature flags prendidos, separados por coma |
| `ENVIRONMENT`    | `development`                        | `production` en Render: entorno de Sentry y oculta `/api/sentry-debug` |
| `SENTRY_DSN`     | — (sin default)                      | Habilita el envío de errores y trazas a Sentry |

> `DB_PATH` es relativo a `backend/`.

## Feature flags

Se prenden con `FEATURES=a,b` en `.env` (local) o en el dashboard de Render.

## Tests

```bash
.venv/bin/pytest              # todo menos las cifras publicadas (default, segundos)
.venv/bin/pytest -m published  # sólo las cifras publicadas (~21k casos, minutos)
.venv/bin/pytest -m ""         # absolutamente todo
```

Lint de Python con [ruff](https://docs.astral.sh/ruff/), sólo errores reales
(imports/variables sin usar, nombres indefinidos, sintaxis — ver `ruff.toml`):

```bash
.venv/bin/ruff check backend tests db
```

## CI (GitHub Actions)

`.github/workflows/ci.yml` corre en cada push a `main` y en cada PR, en una
máquina limpia:

- **frontend** — `npm ci`, `npm run format:check`, `npm run build`.
- **backend** — dos veces, con `FEATURES` vacío y con `olas_2016_2019`:
  `ruff check`, `python db/build_db.py` (la BD no se versiona) y `pytest`.
- **published** — en paralelo, sólo sin flags (la config de producción):
  `python db/build_db.py` y `pytest -m published`. Es el que detecta cuando un
  cambio de datos (olas, overlays, conceptos) mueve una cifra publicada; tarda
  unos minutos y es el que más retrasa el deploy.

El resultado se ve en la pestaña **Actions** del repo y como ✅/❌ junto a cada
commit. Para reproducirlo en local basta con los comandos de arriba. Sin
`GEMINI_API_KEY` el modo IA está apagado, así que CI nunca gasta cuota de Gemini.

Render tiene Auto-Deploy en **"After CI Checks Pass"** (dashboard → Settings):
un push a `main` con CI en rojo no se despliega.

Suites en `tests/`:

- `test_run_query.py` — las 4 formas del motor + invariantes (base Capa A,
  centinelas, ponderación, colapso de ciudades, guard de inyección).
- `test_endpoints.py` — endpoints de la API.
- `test_chat_helpers.py` — helpers del modo IA.
- `test_ratelimit.py` — rate limiting.
- `test_published_figures.py` — cifras publicadas vs. la BD.

## Reconstruir la BD

Ver [pipeline-datos.md](pipeline-datos.md). Un solo comando: construye las olas,
aplica los overlays y arma la capa de conceptos en memoria (no genera CSVs).

```bash
.venv/bin/python db/build_db.py          # reconstruye data/encuesta_multianual.duckdb
```

Los conceptos (comparación entre años) se declaran a mano en
`db/concepts/concept_equivalences.csv` — editarlo y volver a correr `build_db.py`.
Ver [conceptos.md](conceptos.md).

## Deploy (Render.com)

El servicio se configura **en el dashboard de Render** (Settings), no con
`render.yaml`: Render no aplica ese archivo a este servicio. `render.yaml` se
conserva como copia de referencia y hay que mantenerlo a mano igual al dashboard.

| Campo (Settings) | Valor                                                                                                     |
| ---------------- | --------------------------------------------------------------------------------------------------------- |
| Build Command    | `pip install -r requirements.txt && python db/build_db.py && cd frontend && npm install && npm run build` |
| Start Command    | `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`                                              |
| `DB_PATH`        | `/opt/render/project/src/data/encuesta_multianual.duckdb`                                                 |

La BD no se versiona: el build la construye con `db/build_db.py` a partir de los
insumos versionados (tarda unos segundos). El Build Command va en **una sola
línea** encadenada con `&&`, así el build se detiene en el primer paso que falle.
Sin eso, un `build_db.py` fallido no tumba el build: el deploy pasa sin BD y la
app truena al arrancar con `database does not exist`.

Las variables de entorno (`DB_PATH`, `STATIC_DIR`, `GEMINI_API_KEY`, `FEATURES`, `ENVIRONMENT`, `SENTRY_DSN`,
límites del chat) también viven en el dashboard; `render.yaml` lista los valores de referencia.

Flujo típico:

1. Hacer cambios, reconstruir la BD y correr tests y `ruff` localmente.
2. Commitear los insumos que cambiaron (CSVs de olas, overlays, conceptos) — nunca el `.duckdb`.
3. `git push` a `main`; Render despliega cuando CI pasa. Si no arranca solo, **Manual Deploy → Deploy latest commit**.
4. Si cambia el build, el arranque o una variable, actualizar el dashboard **y** `render.yaml`.

## Estructura del repo

```
eav-queries/
├── backend/
│   ├── main.py          # Arma la app FastAPI (middleware, routers, static)
│   ├── routers/         # Capa HTTP: endpoints delgados
│   ├── services/        # Reglas de negocio, orquestación y cachés
│   ├── services/query/  # Motor de consultas, builder SQL seguro
│   ├── repositories/    # Único lugar con texto SQL fijo
│   ├── db_runtime.py    # Conexión DuckDB de solo lectura
│   ├── services/chat/   # Modo IA: prompts, SDK, tool use
│   ├── metadata.py      # Rollups geográficos, recodes, presets, órdenes
│   └── ratelimit.py     # Rate limiting del modo IA
├── frontend/
│   ├── src/             # SPA Vue 3 + Vite
│   └── dist/            # Build
├── db/
│   ├── schema.sql       # DDL multi-año
│   ├── build_db.py      # Construye la BD (olas + overlays + conceptos, sin CSVs intermedios)
│   ├── waves/{2021..2024}/  # CSVs por ola (del ETL)
│   ├── concepts/        # equivalencias entre olas (a mano) + bootstrap_pairs.py
│   └── overlays/        # correcciones al catálogo crudo (a mano)
├── data/
│   ├── source/<año>/                # materia prima del ETL (Cuestionario + EAV .xlsx)
│   ├── waves/<año>/                 # insumos por ola (CSV del ETL; 2025 = BD original intacta)
│   └── encuesta_multianual.duckdb   # BD multi-año que lee la app (build_db.py)
├── docs/                # Documentación
├── tests/               # Suite pytest
└── render.yaml          # Referencia de la config de Render (no se aplica; ver Deploy)
```

Ver también: [arquitectura.md](arquitectura.md) ·
[pipeline-datos.md](pipeline-datos.md) · [conceptos.md](conceptos.md).
