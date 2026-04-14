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
uv run python -m src.assist.cli ingest --target-school UCLA --target-major "Computer Science"
uv run python -m src.assist.cli query --target-school UCLA --target-major "Computer Science"

# Schedule CLI
uv run python -m src.schedule.cli query --target-school UCLA --target-major "Computer Science" --term "Summer 2026"
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
- `service.py` — `ScheduleService`: queries ASSIST DB then calls schedule providers
- `term.py` — parses term labels like `"Summer 2026"` into provider-specific formats

**Scrapers** (each implements `ScheduleProvider`):
- `banner_ellucian.py` — Banner/Ellucian (majority of CA CCs)
- `banner_ssb_classic.py` — Banner SSB Classic variant (MtSAC, CCSF)
- `vsb_4cd.py` — VSB 4CD system (DVC, LMC, CCC)
- `wvm_static.py` — WVM static schedule

### Web Layer (`src/web/`)

FastAPI app serving a search UI.

- `app.py` — mounts static files, templates, CORS middleware
- `routers/schools.py` — `GET /api/schools`, `GET /api/majors`
- `routers/search.py` — `GET /api/search` (joins ASSIST + schedule data)
- `join.py` — `join_results()` merges articulation rows with schedule availability
- `templates/index.html` — single-page frontend

## Key Design Decisions

**ASSIST XSRF handshake:** The ASSIST API requires a homepage request first to obtain a session cookie and `X-XSRF-TOKEN`. All API calls must include this header. See `src/assist/http.py`.

**Major label matching:** ASSIST labels include suffixes like `"Computer Science/B.S."`. Matching strips the suffix for comparison but avoids false positives from composites like `"Computer Science and Engineering/B.S."`.

**Agreement keys are strings:** Some ASSIST report keys are path-like strings, not integers. Never cast them to `int`.

**Provider pattern:** Adding a new CC schedule system = implement `ScheduleProvider` protocol + register in `CompositeProvider`. No other changes needed.

**SQLite at `data/assist.sqlite3`:** Tables are `ingest_runs` and `articulation_rows`. The DB is populated by the ASSIST ingest pipeline before schedule queries can work.
