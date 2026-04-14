# Community College Course Finder

## Problem

Finding community college courses that transfer to a specific university (e.g., UCLA CS) for a given term requires manually cross-referencing two separate systems:

1. **[ASSIST.org](http://ASSIST.org)** — tells you *which* CC courses transfer to your target school/major
2. **Each CC's class schedule** — tells you *whether* that course is actually being offered this term

There is no existing tool that does both in one query. The result: students have to go school-by-school, hand-checking every single CC — extremely tedious.

## Existing Solutions & Limitations

- **[ASSIST.org](http://ASSIST.org)** — official CA articulation system. Covers transferability but has zero schedule data.
- **Transferology** — broader national tool, same limitation. No live term schedule integration.
- `jacobtbigham/ccc_transfers` (GitHub) — scrapes ASSIST for reverse lookup (UCI-specific). No schedule layer.
- `Techwolfy/assist-scraper` (GitHub) — general ASSIST scraper, supports reverse articulation. No schedule layer.
- `Castro19/WebScraping-Assist` (GitHub) — ASSIST scraper feeding a schedule builder. Unfinished.
- **TransferVision** — clean UI over ASSIST data. Read-only, no schedule integration.
- **Plan My Transfer** — free student tool for UC/CSU planning. No live schedule data.

**The gap:** None of them check whether the course is actually being offered in a given term.

## Plan

### v1 — The Dumb Version (prototype, no AI)

Two components:

**1. ASSIST layer** *(implemented here as a first-pass ingest pipeline)*

- Input: target school + major (e.g., UCLA CS)
- Query ASSIST for agreements across CCs, download the corresponding PDF artifacts, and parse simple direct mappings
- Output: normalized articulation rows in SQLite, queryable by target requirement/equivalent (see CLI examples below)

**2. Schedule layer** *(the novel part)*

- For each CC in the result set, hit their class schedule search
- ~80% of CA CCs run on Banner or PeopleSoft — predictable URL/form patterns
- Parse: is this course offered in the target term? Online or in-person?
- Output: filter ASSIST results to only currently-offered courses

**Stack:** Python, `requests` + `pypdf` (ASSIST PDFs); schedule scraping likely `BeautifulSoup` later; maybe `rapidfuzz` if fuzzy matching becomes necessary

**Final output:** "Here are 12 sections of Calc II transferable to UCLA CS, offered Summer 2026 — 5 are online."

### v2 — Where LLMs might genuinely help

Only pull in an LLM if one of these specific problems comes up:

1. **Messy course name matching** — ASSIST says "Calculus II" but CC lists "Calculus for Life Sciences II." LLM fuzzy-matches better than regex.
2. **Non-standard CC portals** — a handful of CCs don't use Banner/PeopleSoft and have custom HTML. LLM-based extractor can parse arbitrary schedule pages without writing one-off scrapers.
3. **Natural language query interface** — e.g., "find me an online async stats course this summer under 3 units that transfers to UCLA" — that's where an LLM earns its place.

Build the dumb version first. Add LLM only when hitting a wall that can't be rule-based out of.

## Current v1 implementation (ASSIST layer)

This repo now includes a first-pass ASSIST ingestion pipeline under `src/assist`.

- `src/assist/discovery.py` resolves institutions and agreement references.
- `src/assist/fetch.py` downloads and caches agreement artifacts.
- `src/assist/parser.py` runs a minimal deterministic parser for direct mappings.
- `src/assist/store.py` persists normalized articulation rows in SQLite.
- `src/assist/cli.py` provides ingest/query commands.

Artifacts are cached under `data/assist_artifacts/`, and the local SQLite database lives at `data/assist.sqlite3`.

### Local environment

This project uses `uv` with a repo-local `.venv`.

```bash
uv python install 3.12
uv venv --python 3.12
source .venv/bin/activate
uv sync
```

### Run tests

```bash
uv run pytest
```

### Run the web UI (prototype)

This repo includes a small FastAPI-backed web UI under `src/web` that joins ASSIST articulation rows with schedule availability for a given term.

```bash
uv run uvicorn src.web.app:app --reload
```

Open `http://127.0.0.1:8000` and search by university, major, term, and optional requirement filter.

Results UX notes:

- Grouped by UC requirement.
- Sorted within each group by availability: Offered → Not offered → Articulation only.
- Availability filter lets you show only one status.
  - "Articulation only" means the course is articulated in ASSIST, but this term's schedule availability wasn't found for that CC/course.

### Ingest and query (single-target v1)

```bash
uv run python -m src.assist.cli ingest \
  --target-school "University of California, Los Angeles" \
  --target-major "Computer Science" \
  --max-cc 8

uv run python -m src.assist.cli query \
  --target-school "University of California, Los Angeles" \
  --target-major "Computer Science" \
  --requirement "MATH 31B"
```

`--max-cc` caps processing by unique community colleges, not raw ASSIST agreement candidate rows.

If ASSIST changes endpoint routing, you can override `--api-prefix`.

### Schedule query (pilot v1)

The schedule layer now includes a pilot query command under `src/schedule`.

```bash
uv run python -m src.schedule.cli query \
  --target-school "University of California, Los Angeles" \
  --target-major "Computer Science" \
  --term "Summer 2026" \
  --cc-id 2 \
  --requirement "MATH 31B"
```

**College selection:** Default `--cc-id` is `0` (omit the flag): query **all** catalog-backed community colleges that appear in the articulation result. Use a nonzero `--cc-id` to pin one college. `**--cc-name`** accepts a **case-insensitive substring** of a catalog college name and must match **exactly one** entry (otherwise the CLI errors). `**--cc-name`** cannot be used together with a nonzero `**--cc-id`**.

```bash
uv run python -m src.schedule.cli query \
  --target-school "University of California, Los Angeles" \
  --target-major "Computer Science" \
  --term "Summer 2026" \
  --cc-name "West Valley" \
  --requirement "MATH 31B"
```

Current v1 scope:

- Canonical term input is a human label like `"Summer 2026"` (strict `Spring|Summer|Fall YYYY`).
- Schedule request failures are fail-soft per course (`offered=false`, error marker in `raw_summary`).

**Supported colleges and adapters (current):**


| College                       | `cc_id` | Adapter                                                       | Status      |
| ----------------------------- | ------- | ------------------------------------------------------------- | ----------- |
| Evergreen Valley College      | 2       | `banner` — Ellucian COLSS (`PostSearchCriteria` / `Sections`) | works       |
| West Valley College           | 80      | `wvm_static` — `schedule.wvm.edu` static JSON                 | works       |
| Diablo Valley College         | 114     | `vsb_4cd` — VSB `api/class-data` XML                          | works       |
| Los Medanos College           | 61      | `vsb_4cd` — VSB `api/class-data` XML                          | works       |
| Contra Costa College          | 28      | `vsb_4cd` — VSB `api/class-data` XML                          | works       |
| Mount San Antonio College     | 62      | `banner_ssb_classic` — old SSB REST API                       | works       |
| City College of San Francisco | 33      | `banner_ssb_classic` — old SSB REST API (port 8105)           | works       |
| Los Angeles City College      | 3       | `banner` — (LACCD schedule likely not Banner)                 | broken      |
| College of Marin              | 4       | `marin_colleague` — public ASP.NET schedule grid              | works       |
| College of San Mateo          | 5       | `smcccd_colleague` — SMCCD schedule API (`/courses`)          | needs creds |


`banner_ssb_classic` resolves term codes dynamically via `getTerms` (each institution uses a different numeric suffix scheme). Raw snippets only when `SCHEDULE_DEBUG_RAW_SUMMARY=1`.

`vsb_4cd` uses the Visual Schedule Builder (`vsb.4cd.edu`) shared by Diablo Valley, Los Medanos, and Contra Costa colleges. Term codes are derived deterministically (`YYYY` + `10`/`20`/`30` for Summer/Fall/Spring). Campus filtering is applied per-block using the `locations` field.

`smcccd_colleague` uses the documented SMCCD API surface. The public docs expose `/courses`, but live responses require Basic Auth credentials; configure `SMCCD_API_USERNAME` and `SMCCD_API_PASSWORD` to enable live schedule pulls.

## ASSIST integration incident notes

During initial v1 implementation, ingest failed on the first API call with:

- `HTTPError: 400 Client Error` on `https://assist.org/api/institutions`

### Root issues discovered

1. **Session/XSRF handshake requirement**
  - ASSIST API calls required a browser-style session bootstrap first.
  - Calling `/api/`* directly without the initial homepage request and anti-forgery header returned HTTP 400.
2. **Major label matching was too strict/naive**
  - Input like `"Computer Science"` did not always match ASSIST labels like `"Computer Science/B.S."`.
  - A broader substring attempt matched incorrect majors (for example `"Computer Science and Engineering/B.S."`).
3. **Agreement key assumptions were wrong**
  - Some matching report keys were path-like strings, not numeric IDs.
  - Casting report keys to `int` caused failures.

### What was tried (including failed attempts)

- Tried direct `/api/`* calls with basic headers only (`User-Agent`, `Accept`, `Referer`) -> **still 400**.
- Tried homepage bootstrap without forwarding the correct XSRF header -> **still 400**.
- Tried broad major substring matching to capture `/B.S.` suffixes -> **introduced false positives**.

### Final fixes applied

- Added ASSIST session bootstrap in `AssistHttpClient`:
  - perform a homepage request first
  - extract cookie `X-XSRF-TOKEN`
  - send header `X-XSRF-TOKEN` on API calls
  - retry once after a 400 by re-bootstrapping
- Updated major matching to compare against the major base label (`"Computer Science"` vs `"Computer Science/B.S."`) while avoiding unrelated composites.
- Updated agreement key handling to treat keys as strings and only select a year/report when a numeric artifact key is available for artifact download.

### Result

- Ingest no longer fails with HTTP 400 on startup.
- Discovery resolves valid agreements for the requested major.
- Ingest writes nonzero rows in normal runs (for example, `rows_written=14` with `--max-cc 2`).

