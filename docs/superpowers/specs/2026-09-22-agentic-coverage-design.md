# Design: Agent-expanded schedule coverage

Date: 2026-09-22
Status: draft for review
Scope: schedule layer, new onboarding and decision layers, section model, matching stage

## 1. Problem

The app answers "which CC courses transfer to my target, and are they offered this term?"
ASSIST ingest already covers 115 colleges for UCLA CS. Schedule lookup covers 8. For the
other 107 the UI shows "Articulation only", which is the unanswered half of the question.

Adding coverage today means hand-writing one Python adapter per portal family and one
catalog entry per college. That does not scale to the long tail, and the survey below
shows the tail is real.

The original motivation for the project was a student abroad looking for online
asynchronous sections, or synchronous sections at hours that work in their timezone. The
current section model has no meeting times, so that question cannot be answered even for
covered colleges.

## 2. Evidence

A survey of all 115 colleges (2026-09-22, eight parallel agents, curl only, three minutes
per college) produced this picture. Full table in `docs/superpowers/specs/portal-survey-2026-09-22.csv`.

| Replay level | Meaning | Colleges |
|---|---|---|
| L0 | one HTTP request, no cookies | 16 |
| L1 | deterministic bootstrap (cookie, anti-forgery token, term select) then one request | 49 |
| L2 | per-session opaque state chains (ASP.NET viewstate, PeopleSoft ICSID, uncracked Banner 8 variant) | 21 |
| L3 | login wall, bot challenge, or credentials required | 14 |
| unknown / untested | portal not located or not probed in budget | 15 |

| Family | Colleges | L0 or L1 |
|---|---|---|
| Colleague Self-Service | 30 | 27 |
| Custom JSON API | 22 | 14 |
| Banner 9 StudentRegistrationSsb | 14 | 13 |
| Custom HTML | 14 | 6 |
| PeopleSoft | 13 | 0 |
| Banner 8 classic | 7 | 2 |
| VSB, WVM static | 3 | 3 |
| PDF only | 3 | 0 |

Corrections found by hand after the survey:

- Riverside district (Riverside City, Norco, Moreno Valley) was graded L3 because its
  Class Finder is hosted behind a Microsoft application proxy. In a real browser the page
  calls an anonymous SharePoint OData API. One GET with a `$filter` returns sections with
  days, times, instructor, modality, and seats. Correct grade: L0 for all three.
- The survey could not run JavaScript, so it never saw XHR calls. Every "custom" L3 or
  untested grade is suspect until re-checked with a browser.
- Portal drift is live: Mt. SAC and CCSF moved from Banner 8 to Banner 9 (the repo's
  classic adapter for them is stale), Evergreen Valley's host in `colleges.json` is dead,
  College of Marin's search returns 500 on postback.
- Course numbering drift is live: ASSIST lists Riverside's Calc II as `MAT 1B`; the Fall
  2026 schedule lists only `MATH-C2220` (California common course numbering). An exact
  string match returns zero sections for a course with four.

Conclusions that shape the design:

1. Two families (Colleague, Banner 9) are 44 colleges. They deserve conventional adapters.
2. The custom tail (36 colleges, at least 20 replayable) deserves a spec-driven generic
   adapter, not 20 hand-written modules.
3. Hand-writing a PeopleSoft adapter is low value: 9 of 13 are the Los Angeles district
   behind single sign-on, which no anonymous adapter can reach.
4. Onboarding must record with a real browser, and must be re-run on a schedule.
5. Course matching between ASSIST codes and live schedule codes is a first-class problem.

## 3. Goals and non-goals

Goals

- Raise working schedule coverage from 8 colleges to at least 60 without a model in the
  query path.
- Make adding a college a mostly automated, human-approved step rather than a code change.
- Detect when a college's portal or numbering drifts and mark it stale instead of silently
  returning "not offered".
- Capture meeting days, times, and modality so the UI can filter for async online and for
  timezone fit.
- Keep the deterministic core testable with recorded fixtures and no network.

Non-goals

- Logging in to any portal, solving CAPTCHAs, or evading bot walls. L3 colleges stay
  "Articulation only" with a link to their portal.
- A natural-language chat front end. That layers on later and needs coverage first.
- Generated Python adapters. Listed as a stretch, not part of this design.
- Multiple target schools or majors. Nothing here prevents it, but it is not in scope.

## 4. Architecture

Query time stays deterministic. Agents run at onboarding time and on a schedule.

```
                        onboarding time (agent, slow, rare)
   college URL ──► navigate ──► record (browser) ──► pick data request ──► generalize
                                                                      │
                              approval queue ◄── validate (probe) ◄───┘
                                     │
                       writes colleges.json entry  or  data/specs/<cc_id>.json
                                     │
                        query time (deterministic, fast, per search)
   ASSIST rows ──► course matcher ──► CompositeProvider ──► family adapter | generic replay adapter
                                                        │
                                              CourseAvailability (with meetings)
                                                        │
                                                   join ──► UI
```

Four new packages and two modified ones:

| Package | Role | New or modified |
|---|---|---|
| `src/schedule/` | family adapters, generic replay adapter, section model | modified |
| `src/schedule/replay/` | spec format, loader, executor, extractor | new |
| `src/llm/` | `GenerativeModel` protocol and per-vendor backends (Anthropic, Gemini, OpenAI-compatible) | new |
| `src/decisions/` | `DecisionProvider` protocol, Jev backend and generative-model backend, question definitions | new |
| `src/matching/` | course equivalence between ASSIST codes and live schedule codes | new |
| `src/onboard/` | navigate, record, generalize, validate, approve, revalidate | new |
| `src/web/` | expose meetings, modality filter, staleness, review queue endpoints | modified |

## 5. Section model

`src/schedule/models.py` gains meeting detail. All dataclasses stay frozen.

```python
@dataclass(frozen=True)
class Meeting:
    days: tuple[str, ...]          # subset of ("M","T","W","R","F","S","U")
    start_local: time | None       # None for asynchronous
    end_local: time | None
    timezone: str = "America/Los_Angeles"
    location: str = ""             # "ONLINE" or building/room

@dataclass(frozen=True)
class ParsedSection:
    section_id: str
    status: str                    # "open" | "closed" | "waitlist" | "unknown"
    modality: str                  # "async_online" | "sync_online" | "hybrid" | "in_person" | "unknown"
    title: str
    instructor: str
    meetings: tuple[Meeting, ...] = ()
    seats_total: int | None = None
    seats_used: int | None = None
    course_code_as_listed: str = ""   # the code the portal used, e.g. "MATH-C2220"
```

Existing adapters keep working with empty `meetings`. Each adapter is then upgraded to
populate meetings where the portal provides them (Colleague, Banner 9, VSB, and Riverside
all do).

Timezone fit is computed at query time from `meetings`, never stored: given a student
UTC offset, a section is "fits" if every synchronous meeting falls inside a configurable
local window, "async" if it has no timed meetings, else "conflicts".

## 6. Family adapters

### 6.1 Catalog schema v2

`colleges.json` entries gain explicit family names and per-district parameters. The
current `"banner"` value is a misnomer for Colleague Self-Service and is renamed with a
migration in `catalog.py` that accepts both during the transition.

```json
{
  "cc_id": 2,
  "cc_name": "Evergreen Valley College",
  "system": "colleague_selfservice",
  "base_url": "https://selfservice.sjeccd.edu",
  "locations": ["EVC"],
  "params": { "term_format": "{yy}/{SEASON}" },
  "source_url": "...",
  "provenance": { "method": "manual" | "onboard", "verified_at": "2026-09-22", "probe_course": "MATH 1" },
  "status": "active" | "stale" | "unsupported"
}
```

`params` is family-specific and validated by the adapter that owns the family. `status`
and `provenance` are written by the onboarding and revalidation steps.

### 6.2 Banner 9 adapter (new)

`src/schedule/banner9_ssb.py`. Two-step L1 template shared by 14 colleges:

1. `POST {base}/StudentRegistrationSsb/ssb/term/search?mode=search` with `term=<code>`,
   cookie jar on.
2. `GET {base}/StudentRegistrationSsb/ssb/searchResults/searchResults?txt_term=<code>&txt_subject=<subj>&txt_courseNumber=<num>&pageMaxSize=50`.

Response is JSON with `data[]`, each row carrying `meetingsFaculty[].meetingTime` (days as
booleans, `beginTime`, `endTime`, `campus`, `buildingDescription`) and `seatsAvailable`.
Term code format is `{yyyy}{20|30|50|70}` but varies by district; it lives in `params`.

### 6.3 Colleague Self-Service adapter (existing, reconfigured)

`banner_ellucian.py` is renamed `colleague_selfservice.py`. The survey found two things it
must take from `params` rather than assume: the term code format (`2026FA` vs `2026/FA`),
and the exact keyword shape (`{"keyword": "MATH 1"}`, course number required). Both are
discoverable from the portal's `CatalogListing` response and recorded at onboarding.

### 6.4 Stale adapters

`banner_ssb_classic.py` stays for Antelope Valley and Santa Barbara (L0 variants) but Mt.
SAC and CCSF move to Banner 9. Marin and SMCCD entries get `status: "unsupported"` with a
note, since one now errors and the other needs credentials.

## 7. Generic replay adapter

### 7.1 Spec format

One JSON file per college at `src/schedule/data/specs/<cc_id>.json`. A spec is a short
list of HTTP steps plus an extraction block. Placeholders are filled from the query.

```json
{
  "cc_id": 78,
  "cc_name": "Riverside City College",
  "version": 1,
  "recorded_at": "2026-09-22",
  "probe": { "course_code": "MATH-C2220", "term": "Fall 2026" },
  "inputs": {
    "term": { "format": "{yy}{SEASON3}", "seasons": { "Fall": "FAL", "Spring": "SPR", "Summer": "SUM" } },
    "subject": { "from": "course_code", "transform": "subject_upper" },
    "course": { "from": "course_code", "transform": "as_listed" }
  },
  "steps": [
    {
      "id": "search",
      "method": "GET",
      "url": "https://apps-studentrcc.msappproxy.net/schedule/_api/web/lists/getByTitle('ScheduleData_RIV')/items",
      "query": {
        "$filter": "Term eq '{term}' and Primary_x0020_Subject eq '{course}'",
        "$select": "Title,Primary_x0020_Subject,Section_x0020_Number,When,Instructor_x0020_Method_x0020_1,Start_x0020_Time_x0020_1,End_x0020_Time_x0020_1,Day1Mon,Day1Tue,Day1Wed,Day1Thu,Day1Fri,Day1Sat,Day1Sun,Faculty_x0020_Name_x0020_1,Total_x0020_Seats,Seats_x0020_Used,Building_x0020_1",
        "$top": "200"
      },
      "headers": { "Accept": "application/json;odata=nometadata" },
      "captures": {}
    }
  ],
  "extract": {
    "kind": "json",
    "rows": "$.value[*]",
    "fields": {
      "section_id": "$.Section_x0020_Number",
      "title": "$.Title",
      "instructor": "$.Faculty_x0020_Name_x0020_1",
      "seats_total": "$.Total_x0020_Seats",
      "seats_used": "$.Seats_x0020_Used",
      "course_code_as_listed": "$.Primary_x0020_Subject",
      "modality_raw": "$.Instructor_x0020_Method_x0020_1",
      "location": "$.Building_x0020_1",
      "meeting_days": { "booleans": ["$.Day1Mon", "$.Day1Tue", "$.Day1Wed", "$.Day1Thu", "$.Day1Fri", "$.Day1Sat", "$.Day1Sun"] },
      "start_time": "$.Start_x0020_Time_x0020_1",
      "end_time": "$.End_x0020_Time_x0020_1"
    }
  }
}
```

Step primitives, deliberately few:

- `GET` / `POST` with `query`, `form`, `json`, `headers`, placeholders anywhere.
- `captures`: named values pulled from a step's response (cookie name, regex over body,
  CSS selector, JSON path) and usable as placeholders in later steps. This covers L1
  (anti-forgery token, term-select cookie) and the ASP.NET viewstate subset of L2 (capture
  hidden inputs, echo them in the next form).
- `extract.kind`: `json` (JSONPath), `html` (CSS selectors per field), `regex`.
- `fields` map to `ParsedSection` and `Meeting` attributes. Unknown fields are ignored.
  Missing required fields fail validation, not extraction.

What the spec language will not do: loops, conditionals, JavaScript execution, or
authentication. If a portal needs those it is not a replay target.

### 7.2 Executor

`src/schedule/replay/executor.py` runs steps with a per-college `requests.Session`,
fixed timeouts, one retry on connection error, and a per-host rate limit. It returns the
final response body and the capture map. `extractor.py` turns a body plus `extract` into
`ParsedSection` rows. `GenericReplayProvider` in `src/schedule/generic_replay.py`
implements `ScheduleProvider` for `system == "replay"` and is registered last in
`CompositeProvider` so hand-written adapters win when both exist.

Normalization of raw modality strings and time formats is shared with the family
adapters and lives in `src/schedule/normalize.py`: a small table of known tokens
(`OL`, `ONLINE`, `HYB`, `LEC`, `REG MEET`) to the modality enum, with `unknown` as the
fallback. The decision layer can refine `unknown` later; the adapter never guesses.

## 8. Decision layer

### 8.1 Protocol

```python
class DecisionProvider(Protocol):
    def decide(self, state: str | dict, questions: dict[str, Question]) -> dict[str, Answer]: ...

Question = Choice(instructions, criteria: dict[str, str]) | Score(instructions, levels: list[str]) | Boolean(instructions)
Answer   = ChoiceAnswer(choice, probabilities, confidence) | ScoreAnswer(score, probabilities, confidence) | BooleanAnswer(probability)
```

Two backends behind the same protocol:

- `JevDecisionProvider` wraps `typesafe-sdk` (`client.system_one(state, questions)`),
  mapping `Boolean` to Jev's `Noul`. Reads `TYPESAFE_API_KEY`.
- `LlmDecisionProvider` asks whatever `GenerativeModel` is configured (section 8.4) for
  the same answer shape using structured output and a self-reported probability. It
  exists so the project runs without Jev access and so the two can be compared.

Selection is by environment variable `DECISION_PROVIDER=jev|llm|none`. With `none`,
every call site falls back to its deterministic default (exact match, `unknown` modality,
"needs review"). The query path never blocks on a decision call: decisions are made at
onboarding, in the matcher's offline pass, and in a cached per-section modality pass.

### 8.2 Questions

Defined once in `src/decisions/questions.py` so both backends and the eval share them.

| Id | Type | Used by | State |
|---|---|---|---|
| `portal_family` | Choice over family names plus `custom`, `unknown` | onboard.navigate | page URL, title, form field names, script hosts |
| `is_search_form` | Boolean | onboard.navigate | same |
| `next_link` | Choice over visible links, high cardinality | onboard.navigate | link texts and hrefs |
| `data_request` | Choice over recorded requests | onboard.record | method, URL, content type, response snippet per request |
| `validation_plausible` | Score 0..3 | onboard.validate | probe course, extracted rows |
| `course_equivalent` | Boolean | matching | ASSIST code and title, live code and title and description |
| `section_modality` | Choice over modality enum | schedule.normalize (cached) | raw modality tokens, location, meeting presence |

### 8.3 Evaluation

`evals/` holds a hand-labeled set (target: 300 course-equivalence pairs across at least
10 colleges, 200 modality rows) and a runner that reports accuracy, and for
`course_equivalent` a calibration curve per backend. The runner is a CLI, not a test, and
its output is a markdown table checked into `evals/results/`. This is the evidence for
choosing thresholds and the artifact that justifies the backend choice.

### 8.4 Generative model abstraction

Every generative call in the project goes through one small protocol in `src/llm/`, so
the vendor can be swapped by configuration and no other module imports a vendor SDK.

```python
class GenerativeModel(Protocol):
    def complete_structured(self, *, system: str, user: str, schema: dict) -> dict: ...
    def complete_text(self, *, system: str, user: str) -> str: ...
```

- `complete_structured` returns a dict that already validates against `schema`; the
  backend is responsible for retrying once on a schema failure and raising
  `LlmOutputInvalid` after that. Callers never parse prose.
- Backends: `AnthropicModel`, `GeminiModel`, `OpenAICompatibleModel` (covers OpenAI,
  OpenRouter, Ollama, and most cheaper hosted models). Each is one file, reads its own
  API key from the environment, and is the only place its SDK is imported.
- Selection is `LLM_PROVIDER=anthropic|gemini|openai` plus `LLM_MODEL=<model id>`, with
  optional `LLM_BASE_URL` for OpenAI-compatible hosts. Nothing else in the codebase
  names a vendor or a model.
- A `FakeModel` backend returns canned structured outputs for tests.
- Cost and latency per call are logged with the provider and model id so backends can
  be compared on the same onboarding run.

Users of this protocol: `LlmDecisionProvider` (8.1), the `generalize` step of onboarding
(section 10), and nothing in the query path.

## 9. Course matching

### 9.1 Problem

ASSIST rows carry the code as of the agreement year. Live schedules carry the code as of
the term. Common course numbering is rewriting codes statewide through 2027, so exact
match will degrade every term.

### 9.2 Design

`src/matching/` adds a stage between ASSIST rows and schedule lookup.

1. **Candidate generation**, deterministic: exact code, code with separators normalized
   (`MAT 1B` = `MAT-1B` = `MAT1B`), and a `course_aliases` table
   (`cc_id, old_code, new_code, source, confidence, verified_at`). The Riverside "old
   course number / new course number" page is one source; the CCN crosswalk published by
   the state is another; the onboarding probe is a third.
2. **Decision**, when candidates are ambiguous or absent: the adapter fetches the
   subject's section list for the term, and `course_equivalent` is asked for each live
   course in that subject with the ASSIST code and title as state. Probability above the
   accept threshold writes an alias with `source = "decision"`. Between thresholds writes
   a `review` row. Below rejects.
3. **Review queue**: `onboard review` lists pending aliases with evidence, and approving
   one promotes it to `verified`. The web UI shows "matched via alias" on results so the
   user can see why a code changed.

Thresholds are constants in `src/matching/config.py`, set from the eval, not guessed.

## 10. Onboarding agent

`src/onboard/` is a pipeline of small steps, each a pure function of its inputs plus
explicit tool calls, so each can be unit-tested with fakes.

| Step | Input | Output | Tools |
|---|---|---|---|
| `navigate` | college name, ASSIST id, optional start URL | portal URL, family guess | HTTP fetch, link extraction, decisions |
| `record` | portal URL, probe course, term | trace: list of (request, response summary) | Playwright with network capture |
| `pick` | trace | the data-bearing request | decision `data_request` |
| `generalize` | request, probe inputs | draft spec or catalog entry | `GenerativeModel.complete_structured`, schema-validated |
| `validate` | draft, a second probe course | pass/fail with extracted rows and score | executor, decision `validation_plausible` |
| `submit` | validated draft | pending item in review queue | SQLite `onboard_queue` |
| `approve` | pending item | file written, catalog reloaded | CLI |
| `revalidate` | every active college | status update `active` or `stale` | executor |

Rules the agent obeys, enforced in code rather than prompt:

- Never submits a form containing a password field. Never proceeds past a page whose URL
  or title indicates login or a bot challenge. Such colleges are marked `unsupported`
  with the reason.
- Rate limit per host, identifying user agent, and a hard cap of requests per college.
- The generative model produces only data (a spec or catalog entry) validated against a
  JSON schema. It never produces code that is executed.
- Validation uses a probe course different from the recorded one, and requires at least
  one extracted row with a section id and a course code that matches the probe.
- The recording drives the portal like a user (clicks, typing), because programmatic
  value injection does not fire some apps' search handlers.

`revalidate` runs from a CLI and, optionally, a GitHub Actions cron. It re-runs each
college's probe, compares the row count and field completeness to the last run, and
flips `status` to `stale` on failure. The UI renders stale colleges as "schedule data
may be out of date" rather than "not offered".

## 11. Query-time data flow

1. `/api/search` loads ASSIST rows for the target and major.
2. `matching.resolve` maps each `(cc_id, course_code)` to zero or more live codes using
   aliases. No network, no model.
3. `ScheduleService` queries `CompositeProvider` per live code. Family adapters and the
   replay adapter both return `CourseAvailability` with `meetings`. Failures produce a
   `CourseAvailability` with `offered=False` and an error summary, as today.
4. `join_results` merges, computes timezone fit if the request carries a UTC offset, and
   tags results with alias provenance and college status.
5. UI adds two filters, modality and "fits my hours", and shows stale and unsupported
   states distinctly from "not offered".

## 12. Error handling

- Adapters raise `ScheduleLookupError` subclasses (`PortalUnreachable`, `PortalChanged`,
  `ExtractionEmpty`). `ScheduleService` catches them, records the type in
  `raw_summary`, and continues. `PortalChanged` also increments a per-college failure
  counter that `revalidate` reads.
- The replay executor validates every spec at load time against a JSON schema and refuses
  to register a college whose spec fails, logging which field.
- Decision backends raise `DecisionUnavailable` on auth or network failure. Every call
  site has a deterministic fallback and logs that it was used.
- Onboarding steps return typed results, never partial files. A failed `validate` leaves
  no spec on disk.

## 13. Testing

- **Family adapters**: recorded HTTP fixtures per family under `tests/fixtures/<family>/`,
  captured once by the recording step and committed. Tests assert parsed sections and
  meetings, with no network.
- **Replay executor and extractor**: unit tests over the spec primitives with synthetic
  responses, plus the Riverside spec against its recorded fixture.
- **Matching**: table-driven tests for candidate generation; decision backend faked to
  return fixed probabilities to test thresholds and queue writes.
- **Onboarding**: each step tested with fakes for the browser, HTTP, and decision
  provider. One integration test runs the pipeline end to end against fixtures.
- **Decision backends**: contract test that both backends return the same answer shape
  for each question type. Live calls only under an env flag.
- **Evals**: separate from pytest, run manually, results committed.
- Coverage target stays at 80%, and TDD applies to each phase.

## 14. Phasing

Each phase gets its own implementation plan and can ship on its own.

1. **Section model and Banner 9.** `Meeting`, modality enum, `banner9_ssb.py`, Colleague
   rename and `params`, catalog schema v2, UI modality and hours filters. Fixes the stale
   Mt. SAC, CCSF, and Evergreen entries. Roughly 40 colleges reachable.
2. **Replay adapter.** Spec schema, executor, extractor, `GenericReplayProvider`, and
   hand-written specs for Riverside, Norco, Moreno Valley, and two more L0 custom portals
   from the survey. Proves the format before automating it.
3. **Decision layer and matching.** Protocol, both backends, questions, alias table,
   matcher stage, review CLI, eval set and runner.
4. **Onboarding agent and revalidation.** Navigate, record, pick, generalize, validate,
   queue, approve, revalidate. Re-survey the L3 and untested colleges with the browser.
5. **Stretch.** Generated adapters for the L2 residue behind the same validation gate;
   natural-language front door over the existing API.

## 15. Decisions taken

- No model in the query path. Agents work at onboarding and on a schedule.
- Jev is optional and evaluated, not required. Both backends implement one protocol.
- No vendor lock-in for generative calls. Every generative call goes through the
  `GenerativeModel` protocol, and the vendor and model are chosen by environment
  variables so Gemini, an OpenAI-compatible host, or a cheaper model can replace the
  default without code changes.
- Specs are data, validated by schema. No generated code is executed.
- PeopleSoft gets no hand-written adapter in this design.
- L3 colleges stay "Articulation only" with a link. No login, no CAPTCHA, no evasion.
- Common course numbering drift is handled by an alias table with provenance, not by
  editing ASSIST rows.

## 16. Open questions

- Which generative model runs the onboarding steps by default. The abstraction in 8.4
  makes this a configuration choice, not a design choice. Pick the cheapest model that
  passes the onboarding integration test, and record the comparison in `evals/results/`.
- Whether `revalidate` should run in CI on a schedule or only locally. Start local.
- How far to trust survey grades for L1 colleges whose sections were not actually seen
  (five colleges). Treat them as leads for the onboarding agent, not as active entries.
