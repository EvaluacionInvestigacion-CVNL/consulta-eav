# Encuesta NL — Survey Query Builder

A query tool over the *Así Vamos* / Consejo Nuevo León survey: ~15,400 respondents, 1.1M answers, 309 questions. It lets non-technical users build cross-tabulations, weight results to the population, and export them — without writing SQL. An optional natural-language mode maps plain Spanish onto the same validated query layer.

DuckDB (FastAPI backend) + Vue 3 frontend.

> **Documentación técnica** (para el equipo, en español) en [`docs/`](docs/):
> [arquitectura](docs/arquitectura.md) ·
> [pipeline de datos](docs/pipeline-datos.md) ·
> [conceptos / armonización entre años](docs/conceptos.md) ·
> [desarrollo y deploy](docs/desarrollo.md).

---

## Stack

| Layer         | Technology                                         |
|---------------|----------------------------------------------------|
| Database      | DuckDB (embedded, columnar, read-only)             |
| Backend       | Python 3.12 · FastAPI · Pydantic · Uvicorn         |
| AI            | Google Gemini (`google-genai`) with tool use       |
| Frontend      | Vue 3 (Composition API) · Vite · Tailwind CSS v4   |
| Visualization | Chart.js                                           |
| Tests         | pytest (FastAPI TestClient) — 138 tests            |
| Deployment    | Render.com (dashboard; `render.yaml` is reference)  |

---

## Architecture

```
┌──────────────────────┐        /api/*         ┌───────────────────────────┐
│  Vue 3 + Vite SPA     │  ───────────────────► │  FastAPI (Python)         │
│  Tailwind · Chart.js  │  ◄─────────────────── │  • query engine           │
│  manual + AI modes    │     JSON / CSV        │  • safe SQL builder       │
└──────────────────────┘                       │  • LLM tool-use (chat)    │
                                                └─────────────┬─────────────┘
                                                              │ read-only
                                                     ┌────────▼────────┐
                                                     │  DuckDB (EAV)    │
                                                     └─────────────────┘
```

In production FastAPI also serves the built SPA as static files, so the whole app is a single service.

### Data schema (EAV, multi-year)

Every data table carries `wave_id` (survey year) as part of its PK, so waves
2021–2025 coexist without colliding.

```sql
answers               (wave_id, respondent_id, question_id, option_id, value)   -- no PK; ordered physically
options               (wave_id, question_id, option_id) PK, option_label, concept_option_id
questions             (wave_id, q_id) PK, q_text, q_section, q_type, q_notes, q_info, q_block, concept_id
respondent_attributes (wave_id, respondent_id, attribute) PK, question_id, value
responses             (wave_id, respondent_id) PK, is_initial_respondent, nombre, factor_cvnl, city_id
```

The data is stored entity-attribute-value: each `(respondent, question)` pair is a row in `answers`, and demographic filters live in `respondent_attributes`, where `attribute` is a friendly name (`sexo`) keyed to a survey `question_id` and `value` is the `option_id` whose human label comes from `options`. A **concepts** layer (`questions.concept_id`, `concept_options`) harmonizes equivalent questions across waves so results can be compared year-over-year (`group_by="year"`).

---

## Design decisions

### DuckDB as an embedded, read-only file
The dataset is fixed reference data, not transactional. An embedded columnar database removes the need for a separate DB server, makes aggregate scans over 1.1M rows fast, and is a single file (~57 MB) that isn't committed: the deploy build rebuilds it from committed inputs with `db/build_db.py`. Every connection is opened `read_only=True`; the file is never mutated at runtime, which also makes the deployment immutable and trivially reproducible.

### EAV schema
Survey instruments are sparse and irregular — questions appear and disappear across sections, many are conditional, and answer sets differ per question. A wide one-column-per-question table would be mostly nulls and would require migrations as the instrument changes. EAV keeps the storage uniform and lets the query layer treat every question identically.

### Generated SQL with allowlist validation, not an ORM
Queries are composed dynamically (which question, which group-by, which filters), so an ORM buys little. Instead, every user-supplied identifier — `question_id`, `group_by`, each filter `attribute` — is checked against an allowlist derived from the database *before* any SQL string is built. Values are integers coerced through Pydantic. The result is dynamic SQL with no injection surface, and the generated SQL is returned to the client so the query is fully transparent.

### Population projection (`factor_cvnl`)
Raw response counts describe the sample, not Nuevo León. The query engine can restrict to initial respondents and apply each respondent's survey expansion factor to produce population estimates. This is a per-query toggle (`initial_only`) rather than a global mode, because both views are legitimate — analysts need weighted estimates, but data-quality checks need raw counts.

### Sentinel handling
Codes `7777` / `8888` / `9999` (*Not applicable* / *Don't know* / *No answer*) are real responses, so they stay in count and percentage distributions, but they are meaningless as quantities, so they are excluded from numeric statistics (means, etc.). Keeping both behaviors avoids silently biasing aggregates while not hiding non-response from the user.

### Pivot mode returns counts *and* percentages
When grouping by an attribute, the response is two parallel tables — absolute counts and column percentages — each with totals. Percentages alone hide small cell sizes; counts alone make distributions hard to compare across unequal groups. Returning both lets the UI show either without a second round-trip.

### Geographic rollups in metadata, not SQL
41 raw `city_id` codes are collapsed into the 11 Monterrey-metro (AMM) municipalities plus four aggregates (AMM, Periphery, Rest of NL, Nuevo León). These groupings, the canonical display orderings, value recodes, and presets all live in `backend/metadata.py` as plain data — so changing how cities roll up or how income brackets are ordered is a data edit, not a query rewrite.

### Recodes and derived orderings as data
Domain-specific value regroupings (e.g. collapsing transport modes into modal categories) and the canonical order of every categorical (`sexo`, `estudios`, `ingreso`, age buckets…) are declared in `metadata.py`. Age is bucketed via a SQL `CASE` rather than pivoting on individual integer years, since per-year columns are noise for analysis.

### AI mode via tool use, not text-to-SQL
The natural-language mode does not ask the model to emit SQL. The model is given the *same* query functions the UI calls and can only act by invoking them, so every AI answer runs through the identical validated, weighted query path and is reproducible. This keeps the LLM grounded in real results and keeps the injection surface at zero. It is fully optional — without `GEMINI_API_KEY` the app runs in manual mode.

### Caching
Metadata endpoints (`/api/questions`, `/api/attributes`, `/api/cities`) are immutable for the life of the process and are cached with `lru_cache`, so the common path serves from memory.

---

## Running locally

```bash
# Backend (FastAPI) — API on :8000, docs at /docs
cd backend
../.venv/bin/uvicorn main:app --port 8000 --reload

# Frontend (Vite dev server, proxies /api → :8000)
cd frontend
npm install        # first time only
npm run dev        # http://localhost:3000
```

AI mode is optional:

```bash
export GEMINI_API_KEY=your_key_here   # omit to run manual-only
```

Tests:

```bash
./.venv/bin/pytest        # query engine + endpoints
```

---

## API

| Method | Path             | Description                          |
|--------|------------------|--------------------------------------|
| GET    | `/api/questions` | All questions + answer options       |
| GET    | `/api/attributes`| Respondent filter attributes + labels|
| GET    | `/api/cities`    | Distinct municipalities              |
| POST   | `/api/query`     | Run a query → JSON                   |
| POST   | `/api/query/csv` | Run a query → CSV download           |
| POST   | `/api/chat`      | Natural-language query (AI mode)     |
| GET    | `/api/health`    | Health check                         |

**`POST /api/query`**

```json
{
  "question_id": "p1",
  "filters": [{ "attribute": "sexo", "value": 1 }],
  "group_by": "city_id",
  "initial_only": true
}
```

`group_by` accepts `"answer"` (flat distribution), `"city_id"`, or any attribute / recode key. Any value other than `"answer"` switches the response to pivot mode (paired counts + percentages tables).

---

## Project layout

```
eav-queries/
├── backend/
│   ├── main.py        # FastAPI app, query engine, safe SQL builder
│   ├── chat.py        # Gemini tool-use integration (AI mode)
│   └── metadata.py    # Geo rollups, recodes, presets, canonical orderings
├── frontend/
│   └── src/           # Vue 3 + Vite SPA (components, store, API client)
├── tests/             # pytest suite (query engine + endpoints)
├── data/              # Wave inputs (committed) + built DuckDB file (gitignored, never mutated)
└── render.yaml        # Reference copy of the Render config (not applied; set in the dashboard)
```
