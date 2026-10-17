# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A query tool over the *Así Vamos* / Consejo Nuevo León multi-year survey (waves
2021–2025, ~15,400 respondents, 1.1M answers, 309 questions). DuckDB (embedded,
read-only) + FastAPI backend + Vue 3 SPA. Lets non-technical users build
cross-tabs, weight to the population, and export CSV without writing SQL; an
optional Gemini-backed chat mode answers in natural language via the same
validated query path (tool use, not text-to-SQL).

**`docs/` has the deep technical documentation (Spanish), and is the
authoritative source — don't duplicate it here, read it when touching that
area:**
- [`docs/arquitectura.md`](docs/arquitectura.md) — query engine internals, the four query shapes, design decisions.
- [`docs/pipeline-datos.md`](docs/pipeline-datos.md) — how `build_db.py` assembles the DB, overlay files.
- [`docs/conceptos.md`](docs/conceptos.md) — cross-year question/option matching algorithm.
- [`docs/desarrollo.md`](docs/desarrollo.md) — env vars, deploy flow.

## Commands

```bash
# Setup (first time)
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm install

# Run backend — API on :8000, docs at /docs
cd backend && ../.venv/bin/uvicorn main:app --port 8000 --reload

# Run frontend — :3000, proxies /api → :8000
cd frontend && npm run dev

# AI chat mode is opt-in (omit to run manual-only)
export GEMINI_API_KEY=your_key_here

# Tests (repo root; conftest.py adds backend/ to sys.path)
.venv/bin/pytest                                   # full suite
.venv/bin/pytest tests/test_run_query.py::test_pivot_by_attribute   # single test
.venv/bin/pytest -k sentinel                        # by keyword
.venv/bin/pytest -m published                       # published-figures acceptance tests only

# Frontend format (no separate lint script; Prettier is the only formatter)
cd frontend && npm run format          # write
cd frontend && npm run format:check    # CI-style check
cd frontend && npm run build           # → frontend/dist, served by FastAPI in prod

# Rebuild the DuckDB file — one command, does everything: loads all waves,
# applies the overlays, and builds the concepts layer in memory (no generated CSVs).
# Required after changing schema.sql, build_db.py, wave CSVs, an overlay, or
# concept_equivalences.csv.
.venv/bin/python db/build_db.py

# Draft cross-year question pairings when adding a new wave (manual tool, NOT
# part of the build — writes a draft for review, nothing is loaded until you
# move the rows into concept_equivalences.csv by hand)
.venv/bin/python db/concepts/bootstrap_pairs.py --new 2026
```

`data/encuesta_multianual.duckdb` is **gitignored** — it used to be committed,
but git can't delta a binary and the history grew ~57 MB per rebuild. A fresh
clone therefore has **no DB**: run `db/build_db.py` before starting the app or
the tests. Everything the build consumes (`data/waves/`, the overlay and
concept CSVs) *is* committed, so a clean checkout can rebuild it. There
is no live migration path: any change to `db/schema.sql`, `db/build_db.py`, wave
CSVs, or the concepts CSVs means rebuilding the file.

Render rebuilds it too, but the service is configured in the **Render
dashboard**, not by `render.yaml` — Render doesn't apply that file; it's a
reference copy kept in sync by hand. The dashboard Build Command runs
`python db/build_db.py` before the frontend build, chained with `&&` so a failed
DB build fails the deploy instead of shipping an app with no DB (see
`docs/desarrollo.md`). Ask before touching the deploy path.

**Feature flags** (`FEATURES=a,b`, registry `KNOWN_FEATURES` in
`backend/config.py`) are *temporary*: they hide work that's done but not yet
delivered, and must stay trivial to remove — each use is a greppable
`if feature("x")` / `v-if="hasFeature(…)"`, nothing else. `olas_2016_2019` makes
`build_db.py` skip those waves; tests pass with and without each flag. See
`docs/desarrollo.md`.

Two more paths are gitignored on purpose and nothing in the build touches them:
`drafts/etl<year>/` (self-contained, in-progress ETLs for waves 2016–2019 that
only emit CSVs — those waves are **not** loaded) and
`db/concepts/export_equivalencias.py` + `equivalencias.xlsx` (a review export of
the concept pairs, not an input).

## Architecture

```
Vue 3 SPA (Vite, Tailwind v4, Chart.js)  ──/api/*──►  FastAPI (main.py)
  manual mode + chat mode                 ◄─JSON/CSV─  query engine, safe SQL builder
                                                        Gemini tool-use (services/chat/)
                                                              │ read-only
                                                        DuckDB file (EAV, multi-year)
```

In production FastAPI also serves the built SPA (`STATIC_DIR`), so it's one
deployable service (Render.com, configured in the dashboard — see above).

### Data model (EAV, multi-year)

Every data table carries `wave_id` as part of its PK so waves coexist without
colliding; question numbering is **not** stable across years (a question's
`q_id` can change between waves — that's what the concepts layer solves).

```sql
answers               (wave_id, respondent_id, question_id, option_id, value)  -- no PK, ordered physically
options               (wave_id, question_id, option_id) PK, option_label, concept_option_id
questions             (wave_id, q_id) PK, q_text, q_section, q_type, concept_id
respondent_attributes (wave_id, respondent_id, attribute) PK, question_id, value
responses             (wave_id, respondent_id) PK, is_initial_respondent, factor_cvnl, city_id
concepts / concept_options   -- cross-year harmonization catalog, see docs/conceptos.md
```

A row in `answers` holds *either* `option_id` (categorical) *or* `value`
(numeric), never both. `respondent_attributes` is the demographic-filter side
table: `attribute` is a friendly name (`sexo`) keyed to a `question_id`,
`value` is an `option_id` resolved through `options`. Wave 2025 loads from
`data/waves/2025/encuesta.duckdb` (the original single-year DB, kept read-only and never
mutated); waves 2021–2024 load from `data/waves/<year>/*.csv` produced by a
sibling ETL repo (`encuesta-asi-vamos-etl`).

`data/` is organized by pipeline stage, both levels keyed by year:
`source/<year>/` holds the raw material the **external ETL** consumes
(`Cuestionario <year>.xlsx` = the instrument, `EAV <year>.xlsx` = the raw export);
`waves/<year>/` holds what **`build_db.py`** consumes; `encuesta_multianual.duckdb`
is the output. This repo never runs that ETL — the one exception is
`db/overlays/build_option_fixes.py`, which reads the questionnaire to recover
missing option labels. `source/2019/` exists with no matching wave (raw material
kept, wave not loaded); `source/2025/` doesn't exist (that wave came from the
original DB, not the ETL).

### Backend layering

`backend/` is layered and the dependency graph is a DAG, so there are no
deferred imports and no load-order significance:

```
routers/       HTTP only: thin endpoints, zero logic   (catalog, query, health)
services/      reglas, orquestación y los lru_cache    (catalog_service, wave_service, dimension_service, ordering)
services/query/  el motor de consultas (ver abajo)
services/chat/   el modo IA (ver abajo)
repositories/  el único lugar con texto SQL FIJO       (survey, responses, concepts, answers)
db_runtime     get_conn() — dueño de la conexión, soporta `with`
```

`main.py` only wires the app (middleware, routers, static mount) and defines no
endpoints. **A repository here means "where SQL literals live", not a swappable
persistence seam** — the DB is a read-only file baked at build time, tests run
against real data on purpose, and there are no writes, so interfaces/ABCs or a
repo method per endpoint would be pure ceremony. A service that is just
`return repo.x(conn, wave)` should be deleted and the router should call the
repo.

`services/query/` is the one subsystem that **composes SQL at runtime**, so its
own queries don't go through `repositories/` (whose queries are fixed and
parameterized). The fixed lookups it used to inline — question type, concept
members, option catalogs, the sentinel scan — *were* moved to repositories;
what stayed is only the SQL that's assembled per request.

Nothing re-exports: tests import each symbol from its owning module
(`services.query.runner.run_query`, `services.query.models.QueryRequest`,
`services.catalog_service.get_questions`, `db_runtime.get_conn`,
`csv_export._csv_fill_empty`), with only `main.app` coming from `main`.

### Query engine (`backend/services/query/`)

```
models.py           QueryRequest — the input contract
runner.py           run_query: validation + the four output shapes
year_comparison.py  the fifth shape, group_by="year"
sql_builder.py      composed SQL fragments (scope, group expression, filters)
sentinels.py        which codes mean "No sabe/No contesta" instead of data
pivot.py            counts/percentage table assembly + city bucket collapsing
```

`runner` builds a `QueryContext` once (wave, question, weighting, filter SQL,
sentinel exclusion) and every shape reads from it — that's why the shape
builders take a context instead of ten positional arguments. `year_comparison`
receives `run_query` as a **parameter** rather than importing it: the engine
calls the year view and the year view calls the engine back, and injection
keeps that dependency one-way and explicit.

Everything routes through `run_query()`. `group_by` selects one of four output
shapes (flat / pivot × categorical / numeric) plus a fifth, `group_by="year"`,
which only works for questions with a populated `concept_id` and is handled
separately by `year_comparison.compare_across_waves()`. Shared helpers worth knowing before
touching it: `sql_builder.answer_scope_sql` (common FROM/JOIN/WHERE — every
shape starts there, so the base is identical across shapes),
`sql_builder.group_expression_sql` (pivot column expression),
`pivot.collapse_cities_into_buckets` (raw `city_id` → AMM municipality buckets
from `metadata.py`), `pivot.build_counts_and_percentage_rows` (counts +
percentages + Total, shared by the numeric and categorical paths).

`metadata.py` is the hand-maintained lookup layer those helpers read: city
rollups (`AMM_ID`, `PERIFERIA_ID`, `ID_TO_CITY_NAME`), age bins, label and
sort-order overrides (`DESIRED_ORDERS`, `ATTRIBUTE_TO_ORDER_KEY`), `RECODES` (derived group-by attributes
that bucket an existing attribute's option codes — served by `/api/recodes`,
compiled by `_recode_case_sql`), and `PRESETS` (canned breakdowns the sidebar
offers). New buckets/orderings belong here, not in query code.

Filters are `{"attribute": …}` (a friendly attribute or `city_id`) or
`{"question": <any categorical q_id>}` (an extra JOIN on `answers`). In the year
view `services/dimension_service.py` translates them per wave through
`concept_option_id` and is **strict**: a value with no equivalent in some wave
is a 400 naming the missing waves, never a silent fallback to the raw code.
`GET /api/dimensions?question_id=…&mode=year` tells the UI which attributes and
questions cover every wave of the selected question.

Every user-supplied identifier (`question_id`, `group_by`, filter
`attribute`s and `question`s) is validated against an allowlist derived from the DB itself
before any SQL string is built — this is a hand-rolled safe-SQL-builder
pattern, not an ORM, and it's why there's no parametrization gap to watch for
when extending query params. `initial_only` (default true) restricts to
initial respondents and weights by `factor_cvnl` for population estimates.
Sentinels `7777`/`8888`/`9999` (N/A · Don't know · No answer, plus `5555` in
the year view) stay in counts/percentages but are excluded from numeric
aggregates; older waves also use non-standard codes there, so
`sentinels.out_of_range_sentinels_by_question()` treats a suspicious code (`88`,
`99`, `999`…) as a sentinel **only** when it exceeds that question's real maximum — an age of 88
survives, "99 days a week" doesn't. That rule filters `q_type='numerica'`, so it
misses scales a wave stored as `categorica`; in the year view those are caught by
`sentinels.is_sentinel_label` (same regex as `build_db._is_sentinel`,
deliberately reimplemented). The test is always the **label**, never the magnitude — real
categories carry high codes (`2024 p52_5` code 6666 = "no garbage service") and a
blind threshold would delete them. Metadata endpoints (`list_questions`,
`list_attributes`, `list_cities`, etc.) are
`lru_cache`d per-wave — they're safe to cache because the DB file never
mutates at runtime.

### Cross-year concepts (`db/concepts/`)

**Everything is hand-declared in two versioned CSVs; there is no matcher and no
generated intermediate files.** `build_db.py::load_concepts` builds the whole
layer in memory at build time.

- `concept_equivalences.csv` — one row per **pair** of equivalent questions in two
  waves (`wave_a,q_a,wave_b,q_b,ctype,decision,concept_id,source,note`). Pairs
  chain transitively, so a multi-wave concept is built from pairwise rows and
  adding a wave is **adding rows, never touching code**. `decision=exclude`
  documents pairs that must *not* be compared. `concept_id` optionally pins the
  id (used for `attr_*`, which the recodes file references by name); otherwise
  the id derives from the newest member (`c2025_p9_1`) and is stable across
  rebuilds. `source` marks `manual` (team-verified) vs `frozen-auto` (frozen from
  the old fuzzy matcher, not individually verified — audit these first).
- `concept_recodes_approved.csv` — only for options whose **codes changed** across
  waves (sexo 1/2 → 0/1), which pairs can't express. A wave covered by a recode
  contributes exactly the declared mappings and nothing else.

The canonical option catalog is the **union** of member waves' options (newest
wave's label wins, sentinels normalized to 7777/8888/9999), built only for
**categorical** concepts — numeric ones align by value in the year view, so a
catalog would be meaningless. The build warns (never fails) on declared-comparable
pairs whose option codes diverge, on `exclude` pairs pulled together by
transitivity, and on recodes pointing at nonexistent concepts/options.

`bootstrap_pairs.py` is a **manual tool, not part of the build**: it drafts
candidate pairs by text similarity when a new wave lands, writing a separate
draft file that nothing loads until rows are moved over by hand. See
[docs/conceptos.md](docs/conceptos.md).

### AI chat mode (`backend/services/chat/`, `backend/ratelimit.py`)

The model is given the *same* query function the manual UI calls (Gemini tool
use) and can only act by invoking it — it never emits raw SQL, so chat
answers run through the identical validated/weighted path as the manual UI.
Fully optional: without `GEMINI_API_KEY` the app just runs in manual mode.

```
routers/chat.py        endpoints, rate limiting, Gemini error → HTTP status
services/chat/
  prompts.py           the text given to the model — CONTENT, not logic
  gemini.py            the only module that knows the provider is Gemini
  query_tool.py        the `query` tool: declaration, execution, summary
  conversation.py      the tool-use loop (MAX_TOOL_ROUNDS)
```

`prompts.py` is ~40% of the subsystem and is where a new wave or a tone change
lands, so it's kept away from the loop and the SDK — different change rates.
The `google.genai` imports are deferred **inside** functions on purpose (the SDK
is an optional dependency and the app must boot without it); confining them to
`gemini.py` and `query_tool.py` is what lets nothing else care. There is
deliberately **no `LLMProvider` interface**: one provider, so an abstraction over
it would be ceremony — `gemini.py` *is* the seam.

`ratelimit.py` enforces per-IP and global daily caps (`CHAT_RATE_PER_MIN`,
`CHAT_DAILY_GLOBAL`, etc. — set in the Render dashboard; `render.yaml` lists the
free-tier reference values).

### Frontend (`frontend/src/`)

Single reactive store (`store.js`, Vue `reactive` + `computed`) holds all
query/UI/chat state; `api.js` is a thin fetch wrapper with one function per
endpoint and no logic. Components read/write the shared store directly rather
than passing props down a tree — check `store.js` first when tracing how a UI
action turns into a query. Larger components: `Sidebar.vue` (question/filter
picker), `QuestionPicker.vue`, `ResultsPanel.vue` / `PivotTables.vue` /
`ChartView.vue` (result rendering), `ChatPanel.vue` (AI mode, renders Markdown
via `marked` + `dompurify`).

## Tests (`tests/`)

`conftest.py` pins `DB_PATH` to `data/encuesta_multianual.duckdb` with an
absolute path and adds `backend/` to `sys.path` *before* importing `main` —
tests always run against real data, not fixtures/mocks, so collection fails
outright if the DB hasn't been built. Suites (171 tests):
`test_run_query.py` (query engine shapes + invariants — base-count regressions,
sentinel handling, weighting, city collapsing, injection guards, year
comparison), `test_endpoints.py`, `test_chat_helpers.py`, `test_ratelimit.py`,
`test_db_freshness.py`, and `test_published_figures.py` (cross-checks live
query results against figures published in the annual report, cited in
`tests/published_figures.csv`; run standalone with `-m published`).

`test_db_freshness.py` is the guard against the repo's easiest mistake: editing
an input CSV and forgetting to rebuild. It compares DB *content* against
`concept_equivalences.csv`, `concept_recodes_approved.csv` and the three overlays
(not mtimes — git doesn't preserve those). A failure there almost always means
`.venv/bin/python db/build_db.py`, not a data bug — and a stale DB is also what
makes unrelated suites fail with misleading messages.
