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

# Course matching (aliases for renumbered/renamed courses)
uv run python -m src.matching.cli review
uv run python -m src.matching.cli approve 12            # or: reject 12
uv run python -m src.matching.cli discover --cc-id 35 --term "Fall 2026"   # live portals; DECISION_PROVIDER picks the backend
uv run python -m src.matching.cli export

# Decision evals (manual; costs money)
DECISION_PROVIDER=llm LLM_PROVIDER=<vendor> LLM_MODEL=<id> uv run python -m evals.runner course-equivalent

# Optional SDKs (the dev group already installs all of them)
uv sync --extra anthropic   # or: --extra gemini, --extra openai, --extra jev
```

## Architecture

Four-stage pipeline: **ASSIST ingest → course matching → schedule lookup → web/CLI output**

### ASSIST Layer (`src/assist/`)

Ingests articulation data from ASSIST.org into SQLite.

- `http.py` — `AssistHttpClient`: handles session bootstrap + XSRF token handshake (required — direct API calls return 400 without it). Retries once on 400 by re-bootstrapping.
- `discovery.py` — resolves institution IDs and agreement references via ASSIST API
- `fetch.py` — downloads and caches PDF artifacts to `data/assist_artifacts/`
- `parser.py` — deterministic parser for direct CC→UC articulation mappings from PDFs
- `store.py` — persists `ArticulationRow` records to `data/assist.sqlite3`
- `pipeline.py` — orchestrates the full ingest workflow
- `models.py` — `Institution`, `AgreementRef`, `ArticulationRow`, `IngestRun`

### LLM Layer (`src/llm/`)

The one interface every generative call goes through.

- `model.py` — `GenerativeModel` protocol: `complete_structured`, `complete_text`, `call_records`
- `runner.py` — shared plumbing for every backend: a `CallRecord` per attempt, JSON-schema validation, exactly one retry on a schema mismatch, no retry on a refusal
- `anthropic_backend.py`, `gemini_backend.py`, `openai_backend.py` — one file per vendor; each is the only place its SDK is imported
- `config.py` — `model_from_env()` picks the backend from `LLM_PROVIDER`, `LLM_MODEL`, and optional `LLM_BASE_URL`
- `fake.py` — `FakeModel` for tests; no network

### Decision Layer (`src/decisions/`)

Answers named questions about one state, with probabilities so thresholds come from an eval, not a guess.

- `types.py` — `Boolean`/`Choice`/`Score` questions, `BooleanAnswer`/`ChoiceAnswer`/`ScoreAnswer`, `DecisionProvider` protocol, `DecisionUnavailable`
- `questions.py` — the shared questions: `course_equivalent`, `section_modality`
- `llm_provider.py` — `DecisionProvider` backed by a `GenerativeModel`
- `jev_provider.py` — `DecisionProvider` backed by Jev (`typesafe-sdk`: `Noul`, `Choice`, `Score`); the only module that imports the SDK
- `factory.py` — `decision_provider_from_env()`: `DECISION_PROVIDER=jev|llm|none`; `none` (or unset) returns `None` and every call site falls back to a deterministic default

### Matching Layer (`src/matching/`)

Resolves course-code drift (renumbered/renamed courses) between ASSIST and a college's live schedule, offline and per-search with no model calls.

- `codes.py` — `code_key`: `"MAT 1B"` == `"MAT-1B"` == `"MAT1B"`
- `seeds.py` plus `data/course_aliases.csv` and `data/subject_renames.csv` — committed, verified seed data (the RCCD crosswalk and `MAT`→`MATH`-style subject renames)
- `store.py` — the `course_aliases` table in `data/assist.sqlite3`; review-safe upserts
- `resolve.py` — `CourseResolver.live_codes()`: the codes to look a course up under this term (aliases, then a renamed spelling, then the ASSIST code itself), at most 3, read once per search, no network, no model. The last slot is always the ASSIST code itself, so a wrong alias can never hide a course still listed under its old code.
- `formerly.py` — deterministic "(Formerly X)" catalog-note matching
- `discover.py` — the offline discover pass; the subject lister and decision backend are injected
- `cli.py` — `review`, `approve`/`reject`, `add`, `discover`, `export`, `import-rccd`

### Schedule Layer (`src/schedule/`)

Queries live CC schedule systems to check if articulated courses are offered in a given term.

- `providers.py` — `ScheduleProvider` protocol: `supports_source(source)` + `search_course(source, dept, number, term)`
- `composite.py` — `CompositeProvider` dispatches to the right scraper by system type
- `catalog.py` — loads `colleges.json` mapping CC IDs → `CollegeScheduleSource`
- `service.py` — `ScheduleService`: `plan()` picks colleges/courses from the ASSIST DB, `iter_results()` looks colleges up in parallel (one provider + HTTP session per college via `provider_factory`, one college's courses in order, at most 3 lookups per server), resolves each ASSIST code's live codes once per search (`src/matching.load_resolver`), and yields each college as it finishes
- `lookups.py` — merges the per-live-code lookups back under the ASSIST code and records `matched_code` / `match_source` / `match_status`
- `listing.py` — `ListedCourse`, `ListingUnsupported`; Banner 9, Colleague, and replay `listing` blocks can list a whole subject for the discover pass
- `colleague_listing.py` — Colleague Self-Service subject listing (`CatalogListing`, paginated)
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

### Evals (`evals/`)

Hand-labeled seed sets, a runner, and committed results for the decision questions.

- `datasets.py` — loads the JSON-lines seed sets under `data/` (`course_equivalent.jsonl`, `section_modality.jsonl`)
- `runner.py` — scores the `DECISION_PROVIDER`-selected backend against a seed set; manual, costs money, not part of pytest
- `report.py` — renders a markdown report to `results/<date>-<question>-<backend>.md`
- `results/` — committed run outputs; the evidence for the thresholds in `src/matching/config.py`
- Eval tests live in `tests/eval_harness/` (not `tests/evals/`) — a `tests/evals` package would shadow the root `evals` package.

## Key Design Decisions

**ASSIST XSRF handshake:** The ASSIST API requires a homepage request first to obtain a session cookie and `X-XSRF-TOKEN`. All API calls must include this header. See `src/assist/http.py`.

**Major label matching:** ASSIST labels include suffixes like `"Computer Science/B.S."`. Matching strips the suffix for comparison but avoids false positives from composites like `"Computer Science and Engineering/B.S."`.

**Agreement keys are strings:** Some ASSIST report keys are path-like strings, not integers. Never cast them to `int`.

**Provider pattern:** Adding a new CC schedule system = implement `ScheduleProvider` protocol + register in `CompositeProvider`. No other changes needed.

**Replay specs are data, not code:** a spec is a schema-validated JSON file of at most five HTTP steps plus an extraction block. No loops, conditionals, JavaScript, or login. Pagination is a declared, bounded primitive. At runtime an invalid spec is skipped and logged (that college shows "Couldn't check"; every other college still works); the test suite and `cli validate` fail fast on it. `tests/schedule/replay/test_specs_registry.py` requires every `"system": "replay"` catalog entry to have a spec with the same `cc_id` and name. A spec may add an optional `listing` block (steps plus `code`/`title`/`description` rules) that lists a whole `{subject}`; the discover pass uses it, and load-time checks cover it.

**ASSIST re-ingest replaces a college's rows:** schedule queries read every ingest run for a major, so `save_rows` deletes a college's rows from earlier runs once a new run has re-parsed that college's agreement into at least one row. Colleges a run did not reach, or that parse to nothing (likely an ASSIST layout change, logged), keep their rows. After a parser fix, re-run `ingest` (cached PDFs in `data/assist_artifacts/` are reused).

**Course-code drift is handled by aliases, never by editing ASSIST rows.** Each search looks an ASSIST course up under every live code the resolver gives (committed seeds plus SQLite aliases), and the web shows "Matched via alias: listed as MATH-C2220". New aliases come from `matching discover`: first catalog "(Formerly X)" notes, which are deterministic; then, if `DECISION_PROVIDER` is set, `course_equivalent` decisions. The best candidate at or above 0.9 is `accepted`, others at or above 0.5 go to `review`, and the rest are `rejected`. A human `approve`/`reject` is final: no automated pass overwrites it, and a reviewed rejection blocks the same seed pair. The resolver returns at most 3 live codes per ASSIST code, and the last slot is always the ASSIST code itself (at most 2 alias/renamed codes come first), so a wrong alias can never hide a course still listed under its old code. `matching discover` also exits 1 with a one-line message when the college's listing fails (network or portal error); it logs a warning when it falls back (`needs_decider`, `decider_unavailable`). The RCCD site's TLS chain is incomplete for Python, so its crosswalk is committed data, refreshed with `import-rccd` from a saved page.

**No model in the query path.** Decision calls happen only in `matching discover` and `evals.runner`. Vendor SDKs are optional extras, each imported in exactly one file.

**SQLite at `data/assist.sqlite3`:** Tables are `ingest_runs`, `articulation_rows`, and `course_aliases` (created by `src/matching/store.py`). The DB is populated by the ASSIST ingest pipeline before schedule queries can work.
