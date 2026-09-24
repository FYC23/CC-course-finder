# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
uv python install 3.12
uv venv --python 3.12
source .venv/bin/activate
uv sync

# Run all tests
uv run pytest

# Run single test file
uv run pytest tests/schedule/test_service.py

# Run single test by name
uv run pytest -k "test_name"

# Start web UI (http://127.0.0.1:8000)
uv run uvicorn src.web.app:app --reload

# ASSIST CLI
uv run python -m src.assist.cli ingest --target-school "University of California, Los Angeles" --target-major "Computer Science"
uv run python -m src.assist.cli query --target-school "University of California, Los Angeles" --target-major "Computer Science"

# Schedule CLI
uv run python -m src.schedule.cli query --target-school "University of California, Los Angeles" --target-major "Computer Science" --term "Summer 2026"

# Replay-spec CLI (data-driven adapters; run/probe hit live portals)
uv run python -m src.schedule.replay.cli validate
uv run python -m src.schedule.replay.cli run --cc-id 27 --term "Fall 2026" --course "MATH 400"
uv run python -m src.schedule.replay.cli probe
```

## Architecture

Three-layer pipeline: **ASSIST ingest → schedule lookup → web/CLI output**

### ASSIST Layer (`src/assist/`)

Ingests articulation data from ASSIST.org into SQLite.

- `http.py` — `AssistHttpClient`: handles session bootstrap + XSRF token handshake (required — direct API calls return 400 without it). Retries once on 400 by re-bootstrapping.
- `discovery.py` — resolves institution IDs and agreement references via ASSIST API
- `fetch.py` — downloads and caches PDF artifacts to `data/assist_artifacts/`
- `parser.py` — deterministic parser for direct CC→UC articulation mappings from PDFs
- `store.py` — persists `ArticulationRow` records to `data/assist.sqlite3`
- `pipeline.py` — orchestrates the full ingest workflow
- `models.py` — `Institution`, `AgreementRef`, `ArticulationRow`, `IngestRun`

### Schedule Layer (`src/schedule/`)

Queries live CC schedule systems to check if articulated courses are offered in a given term.

- `providers.py` — `ScheduleProvider` protocol: `supports_source(source)` + `search_course(source, dept, number, term)`
- `composite.py` — `CompositeProvider` dispatches to the right scraper by system type
- `catalog.py` — loads `colleges.json` mapping CC IDs → `CollegeScheduleSource`
- `service.py` — `ScheduleService`: `plan()` picks colleges/courses from the ASSIST DB, `iter_results()` looks colleges up in parallel (one provider + HTTP session per college via `provider_factory`, one college's courses in order, at most 3 lookups per server) and yields each college as it finishes
- `term.py` — parses term labels like `"Summer 2026"` into provider-specific formats
- `errors.py` — `ScheduleLookupError`, `PortalChanged` (portal answered in an unexpected shape), `SpecInvalid`
- `generic_replay.py` — `GenericReplayProvider`: `ScheduleProvider` for `system == "replay"`; replays the college's spec from `data/specs/<cc_id>.json` and is registered last in `CompositeProvider`
- `replay/` — the replay engine: `spec.py` (frozen model + `schema.json` validation), `checks.py` (load-time semantic checks: every regex/JSONPath/CSS selector compiles, no name shadowing or duplicate step ids, no rule combinations the extractor would ignore), `registry.py` (loads all specs once; at runtime an invalid spec is skipped and logged, while the test suite and `cli validate` load strictly and fail fast), `inputs.py` (placeholders like `{term}`, `{subject}`, `{number}`), `captures.py` (cookie/regex/json/css/term-lookup), `executor.py` (steps, per-instance cache, bounded pagination, per-host throttle, one retry), `extractor.py` (JSON or HTML rows to `ParsedSection`), `text.py` (shared `stringify`/`element_text` helpers used by `captures.py` and `extractor.py`), `jsonpath.py` (tiny JSONPath subset), `cli.py`

**Scrapers** (each implements `ScheduleProvider`):
- `colleague_selfservice.py` — Ellucian Colleague Self-Service (`/Student/Courses`, ~30 CA CCs); term codes resolved from the portal's `TermFilters`, per-district overrides in `params`
- `colleague_sections.py` — section/meeting parsing for Colleague JSON
- `banner9_ssb.py` — Banner 9 StudentRegistrationSsb (~14 CA CCs); term codes resolved via `getTerms`, optional `params.campus_codes` for shared district portals
- `normalize.py` — shared day/time/modality/status normalization used by every adapter
- `vsb_4cd.py` — VSB 4CD system (DVC, LMC, CCC)
- `wvm_static.py` — WVM static schedule
- `data/specs/*.json` — replay specs: Riverside district (78, 148, 149: SharePoint OData), NOCCCD (71, 134: static JSON with a term lookup), Los Rios (27, 142, 145, 126: HTML cards, paginated)

### Web Layer (`src/web/`)

FastAPI app serving a search UI.

- `app.py` — mounts static files, templates, CORS middleware
- `routers/schools.py` — `GET /api/schools`, `GET /api/majors`
- `routers/search.py` — `GET /api/search` (one-shot JSON) and `GET /api/search/stream` (newline-delimited JSON: `start`, one `college` per finished college, `done`/`error`; the page uses this)
- `join.py` — `join_results()` merges articulation rows with schedule availability
- `templates/index.html` — single-page frontend

## Key Design Decisions

**ASSIST XSRF handshake:** The ASSIST API requires a homepage request first to obtain a session cookie and `X-XSRF-TOKEN`. All API calls must include this header. See `src/assist/http.py`.

**Major label matching:** ASSIST labels include suffixes like `"Computer Science/B.S."`. Matching strips the suffix for comparison but avoids false positives from composites like `"Computer Science and Engineering/B.S."`.

**Agreement keys are strings:** Some ASSIST report keys are path-like strings, not integers. Never cast them to `int`.

**Provider pattern:** Adding a new CC schedule system = implement `ScheduleProvider` protocol + register in `CompositeProvider`. No other changes needed.

**Replay specs are data, not code:** a spec is a schema-validated JSON file of at most five HTTP steps plus an extraction block. No loops, conditionals, JavaScript, or login. Pagination is a declared, bounded primitive. At runtime an invalid spec is skipped and logged (that college shows "Couldn't check"; every other college still works); the test suite and `cli validate` fail fast on it. `tests/schedule/replay/test_specs_registry.py` requires every `"system": "replay"` catalog entry to have a spec with the same `cc_id` and name.

**ASSIST re-ingest replaces a college's rows:** schedule queries read every ingest run for a major, so `save_rows` deletes a college's rows from earlier runs once a new run has re-parsed that college's agreement. Colleges a run did not reach keep their rows. After a parser fix, re-run `ingest` (cached PDFs in `data/assist_artifacts/` are reused).

**Course-code drift is a Phase 3 problem:** Riverside district specs send ASSIST codes as-is (`MAT-1B`), which no longer match live codes (`MATH-C2220`); those courses show "Not offered" until the alias table lands.

**SQLite at `data/assist.sqlite3`:** Tables are `ingest_runs` and `articulation_rows`. The DB is populated by the ASSIST ingest pipeline before schedule queries can work.
