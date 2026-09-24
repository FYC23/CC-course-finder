# Phase 2: Generic Replay Adapter and Hand-Written Specs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a data-driven schedule adapter that replays a short, recorded list of HTTP steps from a per-college JSON spec and extracts sections from JSON or HTML, then prove the format with hand-written specs for nine colleges on three custom portals (Riverside district, NOCCCD, Los Rios).

**Architecture:** A new `src/schedule/replay/` package holds the spec model (frozen dataclasses built from a JSON-schema-validated file), a tiny JSONPath subset, placeholder inputs, response captures, an executor (steps, cache, bounded pagination, per-host throttle, one retry), and an extractor (rows, filters, fields, meetings, modality, status). `GenericReplayProvider` implements `ScheduleProvider` for `system == "replay"` and is registered last in `CompositeProvider`. Specs live at `src/schedule/data/specs/<cc_id>.json` and are loaded once, failing fast on any invalid file. No model, no browser, no login, no new network behavior beyond what each spec declares.

**Tech Stack:** Python 3.12, uv, `requests`, `jsonschema` (spec validation), `beautifulsoup4` + `soupsieve` (CSS selectors for HTML extraction), pytest, typer.

**Spec:** `docs/superpowers/specs/2026-09-22-agentic-coverage-design.md` (sections 7, 11, 12, 13, and phase 2 of section 14). Survey evidence: `docs/superpowers/specs/portal-survey-2026-09-22.csv`. Live portal samples used for every fixture below were fetched on 2026-09-23 and are reproduced verbatim in the tasks.

## Global Constraints

- Python `>=3.12`, run everything with `uv run ...`; tests with `uv run pytest`.
- All dataclasses are `frozen=True`. Never mutate an existing object; build a new one (`dataclasses.replace` or a constructor). Local dicts that are built up inside one function and then wrapped in `MappingProxyType` are fine.
- Files stay under 800 lines; prefer 200–400. Functions under 50 lines. Split rather than grow.
- No LLM, no browser, no login, no CAPTCHA handling anywhere in this phase. Nothing in the query path calls a model.
- No vendor SDKs of any kind. The only new dependencies are `jsonschema`, `beautifulsoup4`, and `soupsieve`.
- The spec language has no loops, conditionals, JavaScript, or authentication. Pagination is a bounded, declared primitive (`max_pages`), not a loop.
- Specs are data validated by schema. Nothing generated is executed.
- Adapters never guess modality. Unknown stays `"unknown"`. A spec may map a portal's exact wording to a modality (`modality.map`); everything else goes through `normalize.normalize_modality`.
- Existing adapters (`banner9_ssb`, `colleague_selfservice`, `vsb_4cd`, `wvm_static`, `marin_colleague`, `smcccd_colleague`) do not change.
- The pytest suite stays offline. Live network checks are explicit manual steps (Task 11, steps 8–10).
- Use `mgrep` for searches, not the built-in Grep or WebSearch tools.
- Commit after every task with a conventional-commit message (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`). Do not add attribution trailers.
- Keep 80% coverage. Run the full suite (`uv run pytest -q`) before every commit; all 455 existing tests plus new ones must pass.

---

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `src/schedule/errors.py` | `ScheduleLookupError`, `PortalChanged`, `SpecInvalid` | create |
| `src/schedule/normalize.py` | add `days_from_text`, `location_is_online`, `status_from_seats`, `compact_code` | modify |
| `src/schedule/replay/__init__.py` | package marker | create |
| `src/schedule/replay/jsonpath.py` | minimal JSONPath subset: `parse_path`, `resolve`, `first` | create |
| `src/schedule/replay/schema.json` | JSON Schema (2020-12) for spec files | create |
| `src/schedule/replay/spec.py` | frozen spec dataclasses, `load_spec(path)`, semantic checks | create |
| `src/schedule/replay/registry.py` | `load_all_specs()` (cached), `load_specs_from(directory)` | create |
| `src/schedule/replay/inputs.py` | placeholder values from term + course code, `render(template, values)` | create |
| `src/schedule/replay/captures.py` | `evaluate_capture(...)` for cookie / regex / json / css / lookup | create |
| `src/schedule/replay/executor.py` | `ReplayExecutor.execute(spec, term=, values=)`, `HostThrottle`, cache, pagination, retry | create |
| `src/schedule/replay/extractor.py` | `extract_sections(bodies, extract, values)`; `JsonRow`, `HtmlRow` | create |
| `src/schedule/replay/cli.py` | `validate`, `run`, `probe` commands for manual live checks | create |
| `src/schedule/generic_replay.py` | `GenericReplayProvider` (`ScheduleProvider` for `system == "replay"`) | create |
| `src/schedule/composite.py` | register `GenericReplayProvider` last | modify |
| `src/schedule/catalog.py` | add `"replay"` to `KNOWN_SYSTEMS` | modify |
| `src/schedule/service.py` | student-facing reason for `PortalChanged` | modify |
| `src/schedule/data/specs/78.json`, `148.json`, `149.json` | Riverside City, Norco, Moreno Valley (SharePoint OData) | create |
| `src/schedule/data/specs/71.json`, `134.json` | Cypress, Fullerton (NOCCCD static JSON) | create |
| `src/schedule/data/specs/27.json`, `142.json`, `145.json`, `126.json` | American River, Cosumnes River, Folsom Lake, Sacramento City (Los Rios HTML) | create |
| `src/schedule/data/colleges.json` | nine `"system": "replay"` entries | modify |
| `tests/fixtures/replay/*` | recorded response samples (JSON and HTML) | create |
| `tests/schedule/replay/*.py` | unit tests per module and per-district spec tests | create |
| `tests/schedule/test_generic_replay.py`, `test_normalize.py`, `test_catalog.py`, `test_service_parallel.py` | provider, normalize, catalog, and error-reason tests | create / modify |
| `README.md`, `CLAUDE.md` | replay adapter, spec format, CLI | modify |

## Spec format at a glance (normative; Tasks 2–10 implement exactly this)

```json
{
  "cc_id": 78, "cc_name": "Riverside City College", "version": 1, "recorded_at": "2026-09-23",
  "notes": "free text",
  "probe": { "course_code": "MATH-C2220", "term": "Fall 2026", "expect_min_rows": 1 },
  "inputs": {
    "term":  { "format": "{yy}{SEASON}", "seasons": { "fall": "FAL", "spring": "SPR", "summer": "SUM" } },
    "named": { "course": { "from": "course_code", "transform": "dash_join" } }
  },
  "steps": [
    { "id": "search", "method": "GET", "url": "https://host/path",
      "query": { "k": "{term}" }, "form": {}, "json": {}, "headers": {},
      "captures": { "name": { "regex": "...(group)..." , "on_missing": "term_not_listed" } },
      "cache": true,
      "paginate": { "param": "offset", "first": 0, "increment": 1, "page_size": 20, "max_pages": 10, "total_capture": "total" } }
  ],
  "extract": {
    "kind": "json", "rows": "$.value[*]",
    "filter": [ { "value": "$.campus", "equals": "1" }, { "value": "$.num", "any_of": ["{number}", "{number}C"] } ],
    "fields": { "section_id": "$.crn", "title": "$.title", "instructor": "$.who",
                "seats_total": "$.max", "seats_used": "$.enrl", "seats_available": "$.avail",
                "wait_capacity": "$.wait", "course_code_as_listed": { "join": ["$.subj", "$.num"] } },
    "status": { "from_seats": true },
    "modality": { "tokens": ["$.method"], "map": { "partially online": "hybrid" } },
    "meetings": [ { "each": "$.meetings[*]",
                    "days": { "flags": ["$.mon", "$.tue", "$.wed", "$.thu", "$.fri", "$.sat", "$.sun"] },
                    "start": "$.begin", "end": "$.end", "location": { "join": ["$.bldg", "$.room"] },
                    "start_date": "$.from", "end_date": "$.to" } ]
  }
}
```

Placeholders always available: `{course_code}`, `{subject}`, `{number}`, `{term_label}`, `{yyyy}`, `{yy}`, `{season}`, `{Season}`. `{term}` exists when `inputs.term` is set or a capture named `term` ran. Named inputs and captures add their own names. A value rule is a bare string (JSONPath for `kind: json`, CSS selector for `kind: html`) or an object with `path` / `css` (+ `attr`), optional `regex` (group 1), `const`, or `join` + `sep`. Captures: `cookie`, `regex`, `json`, `css` (+ `attr`), `lookup` (`rows`, `label`, `value`; picks the row whose label best matches the term via `term_match_rank`). `on_missing` is `portal_changed` (default) or `term_not_listed`. Comparisons in `filter` use `normalize.compact_code` on both sides. `marker` (html only) is a selector that must match or the page counts as changed. A meeting is skipped when it has no days, no start time and no location. `is_online` is `normalize.location_is_online(location)`.

---

### Task 1: Errors, JSONPath subset, and normalize helpers

**Files:**
- Create: `src/schedule/errors.py`
- Create: `src/schedule/replay/__init__.py` (empty)
- Create: `src/schedule/replay/jsonpath.py`
- Modify: `src/schedule/normalize.py`
- Create: `tests/schedule/replay/__init__.py` (empty)
- Test: `tests/schedule/replay/test_jsonpath.py`, `tests/schedule/test_normalize.py`

**Interfaces:**
- Produces: `errors.ScheduleLookupError(Exception)`, `errors.PortalChanged(ScheduleLookupError)`, `errors.SpecInvalid(ValueError)`.
- Produces: `jsonpath.parse_path(path: str) -> tuple[object, ...]`, `jsonpath.resolve(doc, path) -> list[Any]`, `jsonpath.first(doc, path) -> Any | None`, `jsonpath.JsonPathError(ValueError)`, `jsonpath.WILDCARD`.
- Produces: `normalize.days_from_text(raw) -> tuple[str, ...]`, `normalize.location_is_online(location) -> bool`, `normalize.status_from_seats(*, seats_total, seats_used, seats_available, wait_capacity) -> str`, `normalize.compact_code(value) -> str`.

- [ ] **Step 1: Write the failing JSONPath tests**

Create `tests/schedule/replay/__init__.py` (empty) and `tests/schedule/replay/test_jsonpath.py`:

```python
from __future__ import annotations

import pytest

from src.schedule.replay.jsonpath import WILDCARD, JsonPathError, first, parse_path, resolve

_DOC = {
    "value": [
        {"id": "1", "meet": [{"day": "M"}, {"day": "W"}], "seats": 42.0},
        {"id": "2", "meet": [], "seats": None},
    ],
    "odd key": {"x": 1},
    "data": None,
}


def test_parse_path_tokens():
    assert parse_path("$") == ()
    assert parse_path("$.value[*].id") == ("value", WILDCARD, "id")
    assert parse_path("$[0]") == (0,)
    assert parse_path("$[-1]") == (-1,)
    assert parse_path('$["odd key"].x') == ("odd key", "x")
    assert parse_path("$['odd key']") == ("odd key",)


@pytest.mark.parametrize("bad", ["value", "$.", "$..x", "$[a]", "$.a[1:2]", "$.a.b["])
def test_parse_path_rejects_unsupported_syntax(bad):
    with pytest.raises(JsonPathError):
        parse_path(bad)


def test_resolve_root_returns_doc():
    assert resolve(_DOC, "$") == [_DOC]


def test_resolve_wildcard_over_list_and_nested():
    assert resolve(_DOC, "$.value[*].id") == ["1", "2"]
    assert resolve(_DOC, "$.value[*].meet[*].day") == ["M", "W"]


def test_resolve_wildcard_over_dict_values():
    assert resolve({"a": {"n": 1}, "b": {"n": 2}}, "$[*].n") == [1, 2]


def test_resolve_index_and_negative_index():
    assert resolve(_DOC, "$.value[1].id") == ["2"]
    assert resolve(_DOC, "$.value[-1].id") == ["2"]
    assert resolve(_DOC, "$.value[5].id") == []


def test_resolve_missing_key_selects_nothing():
    assert resolve(_DOC, "$.nope") == []
    assert resolve(_DOC, "$.value[*].nope") == []


def test_resolve_null_value_is_a_match():
    assert resolve(_DOC, "$.data") == [None]


def test_resolve_quoted_key():
    assert resolve(_DOC, '$["odd key"].x') == [1]


def test_first():
    assert first(_DOC, "$.value[*].id") == "1"
    assert first(_DOC, "$.nope") is None
```

- [ ] **Step 2: Write the failing normalize tests**

Append to `tests/schedule/test_normalize.py`:

```python
# --- Phase 2 helpers ----------------------------------------------------------

from src.schedule.normalize import (  # noqa: E402
    compact_code,
    days_from_text,
    location_is_online,
    status_from_seats,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Mon/Wed", ("M", "W")),
        ("Tu,Th", ("T", "R")),
        ("MWF", ("M", "W", "F")),
        ("TTh", ("T", "R")),
        ("Saturday", ("S",)),
        ("Sat Sun", ("S", "U")),
        ("Asynchronous – no scheduled meeting times", ()),
        ("", ()),
        (None, ()),
    ],
)
def test_days_from_text(raw, expected):
    assert days_from_text(raw) == expected


@pytest.mark.parametrize(
    "location,expected",
    [
        ("ON LINE", True),
        ("ONLINE ONLINE", True),
        ("ZOOM", True),
        ("Web", True),
        ("MTSC 106", False),
        ("Main Campus, STEM, 310", False),
        ("", False),
        (None, False),
    ],
)
def test_location_is_online(location, expected):
    assert location_is_online(location) is expected


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(seats_total=42, seats_used=36, seats_available=None, wait_capacity=None), "open"),
        (dict(seats_total=42, seats_used=42, seats_available=None, wait_capacity=None), "closed"),
        (dict(seats_total=42, seats_used=45, seats_available=None, wait_capacity=10), "waitlist"),
        (dict(seats_total=None, seats_used=None, seats_available=3, wait_capacity=20), "open"),
        (dict(seats_total=None, seats_used=None, seats_available=0, wait_capacity=20), "waitlist"),
        (dict(seats_total=None, seats_used=None, seats_available=0, wait_capacity=0), "closed"),
        (dict(seats_total=None, seats_used=None, seats_available=None, wait_capacity=None), "unknown"),
    ],
)
def test_status_from_seats(kwargs, expected):
    assert status_from_seats(**kwargs) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("MATH 400", "MATH400"),
        ("math-400", "MATH400"),
        ("009 C", "9C"),
        ("150AC", "150AC"),
        ("American River College", "AMERICANRIVERCOLLEGE"),
        ("", ""),
        (None, ""),
    ],
)
def test_compact_code(value, expected):
    assert compact_code(value) == expected
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_jsonpath.py tests/schedule/test_normalize.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.schedule.replay'` and `ImportError: cannot import name 'compact_code'`.

- [ ] **Step 4: Create the errors module and package markers**

Create `src/schedule/errors.py`:

```python
"""Exception types shared by schedule adapters and the replay engine."""
from __future__ import annotations


class ScheduleLookupError(Exception):
    """A lookup failed for a reason the adapter understands (not a plain network error)."""


class PortalChanged(ScheduleLookupError):
    """The portal answered, but not in the shape the adapter or spec expects."""


class SpecInvalid(ValueError):
    """A replay spec file failed validation. The message names the file and the field."""
```

Create empty files `src/schedule/replay/__init__.py` and `tests/schedule/replay/__init__.py`.

- [ ] **Step 5: Implement the JSONPath subset**

Create `src/schedule/replay/jsonpath.py`:

```python
"""A deliberately small JSONPath subset for replay specs.

Supported: ``$``, ``.name``, ``["quoted name"]`` / ``['quoted name']``, ``[N]`` (an
integer index, negative allowed) and ``[*]`` (every element of a list, or every value of
an object). Nothing else: no filters, recursion, slices or unions. Specs are recorded
data, and a tiny path language keeps extraction deterministic and easy to test.
"""
from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(
    r"""\.([A-Za-z0-9_\-]+)            # .name
      | \[\*\]                          # [*]
      | \[(-?\d+)\]                     # [N]
      | \[(?:"([^"]*)"|'([^']*)')\]     # ["name"] or ['name']
    """,
    re.VERBOSE,
)


class JsonPathError(ValueError):
    """The path uses syntax outside the supported subset."""


class _Wildcard:
    def __repr__(self) -> str:
        return "[*]"


WILDCARD = _Wildcard()


def parse_path(path: str) -> tuple[object, ...]:
    """Split ``$.a[*].b`` into ``('a', WILDCARD, 'b')``. Raises JsonPathError otherwise."""
    if not path.startswith("$"):
        raise JsonPathError(f"JSONPath must start with '$': {path!r}")
    tokens: list[object] = []
    pos = 1
    while pos < len(path):
        match = _TOKEN_RE.match(path, pos)
        if match is None:
            raise JsonPathError(f"Unsupported JSONPath syntax at offset {pos} in {path!r}")
        tokens.append(_token_of(match))
        pos = match.end()
    return tuple(tokens)


def _token_of(match: re.Match[str]) -> object:
    name, index, dq_name, sq_name = match.groups()
    if name is not None:
        return name
    if index is not None:
        return int(index)
    if dq_name is not None:
        return dq_name
    if sq_name is not None:
        return sq_name
    return WILDCARD


def resolve(doc: Any, path: str) -> list[Any]:
    """Every value the path selects, in document order. Missing keys select nothing;
    a key whose value is ``null`` selects ``None``."""
    current: list[Any] = [doc]
    for token in parse_path(path):
        current = [child for node in current for child in _step(node, token)]
    return current


def first(doc: Any, path: str) -> Any | None:
    matches = resolve(doc, path)
    return matches[0] if matches else None


def _step(node: Any, token: object) -> list[Any]:
    if token is WILDCARD:
        if isinstance(node, list):
            return list(node)
        if isinstance(node, dict):
            return list(node.values())
        return []
    if isinstance(token, int):
        if isinstance(node, list) and -len(node) <= token < len(node):
            return [node[token]]
        return []
    if isinstance(node, dict) and token in node:
        return [node[token]]
    return []
```

- [ ] **Step 6: Add the normalize helpers**

Append to `src/schedule/normalize.py` (after the existing `_modality_from_meetings`):

```python
# --- Phase 2 helpers used by the replay extractor ---------------------------------

_DAY_NAME_TO_CODE: Mapping[str, str] = {
    "m": "M", "mo": "M", "mon": "M", "monday": "M",
    "t": "T", "tu": "T", "tue": "T", "tues": "T", "tuesday": "T",
    "w": "W", "we": "W", "wed": "W", "wednesday": "W",
    "r": "R", "th": "R", "thu": "R", "thur": "R", "thurs": "R", "thursday": "R",
    "f": "F", "fr": "F", "fri": "F", "friday": "F",
    "s": "S", "sa": "S", "sat": "S", "saturday": "S",
    "u": "U", "su": "U", "sun": "U", "sunday": "U",
}
# A run of day letters with no separators, e.g. "MWF" or "TTh".
_COMPACT_DAYS_RE = re.compile(r"^(?:th|sa|su|[mtwrfsu])+$")
_COMPACT_DAY_PIECE_RE = re.compile(r"th|sa|su|[mtwrfsu]")
_ONLINE_LOCATION_WORDS = frozenset(
    {"on", "onl", "online", "web", "internet", "distance", "remote", "zoom", "virtual"}
)
_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")
_DIGIT_PREFIX_RE = re.compile(r"^(\d*)(.*)$")


def days_from_text(raw: object) -> tuple[str, ...]:
    """'Mon/Wed', 'Tu,Th', 'MWF', 'TTh' or 'Saturday' to day codes in weekday order.
    Words that are not day names (e.g. 'Asynchronous') contribute nothing."""
    if not isinstance(raw, str):
        return ()
    present: set[str] = set()
    for token in re.findall(r"[A-Za-z]+", raw.lower()):
        code = _DAY_NAME_TO_CODE.get(token)
        if code is not None:
            present.add(code)
        elif _COMPACT_DAYS_RE.match(token):
            present.update(_DAY_NAME_TO_CODE[p] for p in _COMPACT_DAY_PIECE_RE.findall(token))
    return tuple(code for code in DAY_CODES if code in present)


def location_is_online(location: object) -> bool:
    """True when a meeting location names an online venue ('ON LINE', 'ONLINE', 'ZOOM')."""
    if not isinstance(location, str):
        return False
    return bool(frozenset(_WORD_RE.findall(location.lower())) & _ONLINE_LOCATION_WORDS)


def status_from_seats(
    *,
    seats_total: int | None,
    seats_used: int | None,
    seats_available: int | None,
    wait_capacity: int | None,
) -> str:
    """Derive open/closed/waitlist from seat counts when the portal has no status field."""
    available = seats_available
    if available is None and seats_total is not None and seats_used is not None:
        available = seats_total - seats_used
    if available is None:
        return "unknown"
    if available > 0:
        return "open"
    if wait_capacity is not None and wait_capacity > 0:
        return "waitlist"
    return "closed"


def compact_code(value: object) -> str:
    """Uppercase, keep only letters and digits, and drop leading zeros from a leading digit
    run, so 'MATH 400', 'MATH-400' and 'math400' compare equal and '009 C' equals '9C'."""
    if not isinstance(value, str):
        return ""
    cleaned = _NON_ALNUM_RE.sub("", value).upper()
    digits, rest = _DIGIT_PREFIX_RE.match(cleaned).groups()
    if digits:
        digits = digits.lstrip("0") or "0"
    return f"{digits}{rest}"
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_jsonpath.py tests/schedule/test_normalize.py -q`
Expected: all PASS.

- [ ] **Step 8: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add src/schedule/errors.py src/schedule/replay/__init__.py src/schedule/replay/jsonpath.py src/schedule/normalize.py tests/schedule/replay/__init__.py tests/schedule/replay/test_jsonpath.py tests/schedule/test_normalize.py
git commit -m "feat(schedule): add replay errors, JSONPath subset, and seat/day/location helpers"
```

---

### Task 2: Spec model, JSON schema, loader, and registry

**Files:**
- Create: `src/schedule/replay/schema.json`
- Create: `src/schedule/replay/spec.py`
- Create: `src/schedule/replay/registry.py`
- Modify: `pyproject.toml` (add `jsonschema`)
- Test: `tests/schedule/replay/test_spec.py`

**Interfaces:**
- Consumes: `errors.SpecInvalid` (Task 1).
- Produces frozen dataclasses in `spec.py`: `ValueRule(path, css, attr, regex, const, join, sep)`, `Capture(kind, arg, attr, lookup_label, lookup_value, on_missing)`, `Paginate(param, total_capture, page_size, first, increment, max_pages)`, `Step(id, method, url, query, form, json_body, headers, captures, cache, paginate)`, `FilterRule(value, equals, any_of)`, `MeetingRule(each, day_flags, day_text, time_text, time_pattern, start, end, location, start_date, end_date)`, `Extract(kind, rows, marker, filters, fields, status, status_from_seats, modality_tokens, modality_map, meetings)`, `TermInput(format, seasons)`, `NamedInput(source, transform)`, `SpecInputs(term, named)`, `Probe(course_code, term, expect_min_rows)`, `ReplaySpec(cc_id, cc_name, version, recorded_at, probe, inputs, steps, extract, source_path)`.
- Produces: `spec.load_spec(path: Path) -> ReplaySpec`, `spec.value_rule(raw, kind) -> ValueRule`, `spec.BUILTIN_PLACEHOLDERS`, `spec.FIELD_NAMES`.
- Produces: `registry.load_all_specs() -> Mapping[int, ReplaySpec]` (cached), `registry.load_specs_from(directory: Path) -> Mapping[int, ReplaySpec]`, `registry.SPECS_DIR`.

- [ ] **Step 1: Add the dependency**

Run: `uv add "jsonschema>=4.23"`
Expected: `pyproject.toml` gains `"jsonschema>=4.23"` under `dependencies` and `uv.lock` updates.

- [ ] **Step 2: Write the failing tests**

Create `tests/schedule/replay/test_spec.py`:

```python
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.schedule.errors import SpecInvalid
from src.schedule.replay.registry import load_specs_from
from src.schedule.replay.spec import Capture, Paginate, ValueRule, load_spec, value_rule

MINIMAL = {
    "cc_id": 999,
    "cc_name": "Test College",
    "version": 1,
    "recorded_at": "2026-09-23",
    "probe": {"course_code": "MATH 1", "term": "Fall 2026"},
    "inputs": {"term": {"format": "{yyyy}{SEASON}", "seasons": {"fall": "70"}}},
    "steps": [
        {"id": "search", "method": "GET", "url": "https://example.edu/api",
         "query": {"term": "{term}", "subj": "{subject}"}}
    ],
    "extract": {"kind": "json", "rows": "$.data[*]", "fields": {"section_id": "$.crn"}},
}


def _write(tmp_path: Path, data: dict, name: str = "999.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def _variant(**changes) -> dict:
    data = copy.deepcopy(MINIMAL)
    for key, value in changes.items():
        data[key] = value
    return data


def test_load_minimal_spec(tmp_path: Path):
    spec = load_spec(_write(tmp_path, MINIMAL))
    assert spec.cc_id == 999
    assert spec.probe.expect_min_rows == 1
    assert spec.inputs.term is not None and spec.inputs.term.seasons["fall"] == "70"
    assert spec.steps[0].query["term"] == "{term}"
    assert spec.steps[0].cache is False and spec.steps[0].paginate is None
    assert spec.extract.fields["section_id"] == ValueRule(path="$.crn")
    assert spec.source_path.endswith("999.json")


def test_missing_required_key_names_field(tmp_path: Path):
    data = _variant()
    del data["steps"]
    with pytest.raises(SpecInvalid, match="steps"):
        load_spec(_write(tmp_path, data))


def test_unknown_top_level_key_rejected(tmp_path: Path):
    with pytest.raises(SpecInvalid, match="surprise"):
        load_spec(_write(tmp_path, _variant(surprise=1)))


def test_unknown_field_name_rejected(tmp_path: Path):
    extract = {"kind": "json", "rows": "$.d[*]", "fields": {"section_id": "$.a", "colour": "$.b"}}
    with pytest.raises(SpecInvalid, match="colour"):
        load_spec(_write(tmp_path, _variant(extract=extract)))


def test_unreadable_json_is_spec_invalid(tmp_path: Path):
    path = tmp_path / "999.json"
    path.write_text("{not json")
    with pytest.raises(SpecInvalid, match="cannot read"):
        load_spec(path)


def test_unknown_placeholder_rejected(tmp_path: Path):
    steps = [{"id": "s", "method": "GET", "url": "https://example.edu/{mystery}"}]
    with pytest.raises(SpecInvalid, match="mystery"):
        load_spec(_write(tmp_path, _variant(steps=steps)))


def test_capture_from_earlier_step_is_a_known_placeholder(tmp_path: Path):
    steps = [
        {"id": "boot", "method": "GET", "url": "https://example.edu/",
         "captures": {"token": {"regex": "name=\"tok\" value=\"([^\"]+)\""}}},
        {"id": "search", "method": "POST", "url": "https://example.edu/api",
         "form": {"tok": "{token}", "term": "{term}"}},
    ]
    spec = load_spec(_write(tmp_path, _variant(steps=steps)))
    assert spec.steps[0].captures["token"] == Capture(kind="regex", arg='name="tok" value="([^"]+)"')


def test_capture_used_before_defined_rejected(tmp_path: Path):
    steps = [
        {"id": "search", "method": "GET", "url": "https://example.edu/{token}"},
        {"id": "boot", "method": "GET", "url": "https://example.edu/",
         "captures": {"token": {"cookie": "tok"}}},
    ]
    with pytest.raises(SpecInvalid, match="token"):
        load_spec(_write(tmp_path, _variant(steps=steps)))


def test_regex_quantifier_braces_are_not_placeholders(tmp_path: Path):
    steps = [{"id": "s", "method": "GET", "url": "https://example.edu/",
              "captures": {"term": {"regex": "for=\"(\\d{4})\">\\s*{term_label}"}}}]
    spec = load_spec(_write(tmp_path, _variant(steps=steps, inputs={})))
    assert spec.steps[0].captures["term"].arg == 'for="(\\d{4})">\\s*{term_label}'


def test_paginate_only_on_last_step(tmp_path: Path):
    paginate = {"param": "offset", "page_size": 20, "total_capture": "total"}
    steps = [
        {"id": "a", "method": "GET", "url": "https://example.edu/a",
         "captures": {"total": {"css": "#total"}}, "paginate": paginate},
        {"id": "b", "method": "GET", "url": "https://example.edu/b"},
    ]
    with pytest.raises(SpecInvalid, match="last step"):
        load_spec(_write(tmp_path, _variant(steps=steps)))


def test_paginate_total_capture_must_exist(tmp_path: Path):
    steps = [{"id": "a", "method": "GET", "url": "https://example.edu/a",
              "paginate": {"param": "offset", "page_size": 20, "total_capture": "total"}}]
    with pytest.raises(SpecInvalid, match="total"):
        load_spec(_write(tmp_path, _variant(steps=steps)))


def test_paginate_defaults(tmp_path: Path):
    steps = [{"id": "a", "method": "GET", "url": "https://example.edu/a",
              "captures": {"total": {"css": "#total"}},
              "paginate": {"param": "offset", "page_size": 20, "total_capture": "total"}}]
    spec = load_spec(_write(tmp_path, _variant(steps=steps)))
    assert spec.steps[0].paginate == Paginate(
        param="offset", total_capture="total", page_size=20, first=0, increment=1, max_pages=10
    )


def test_json_rows_must_end_with_wildcard(tmp_path: Path):
    extract = {"kind": "json", "rows": "$.data", "fields": {"section_id": "$.crn"}}
    with pytest.raises(SpecInvalid, match=r"\[\*\]"):
        load_spec(_write(tmp_path, _variant(extract=extract)))


def test_css_rule_rejected_in_json_spec(tmp_path: Path):
    extract = {"kind": "json", "rows": "$.d[*]", "fields": {"section_id": {"css": "li"}}}
    with pytest.raises(SpecInvalid, match="css"):
        load_spec(_write(tmp_path, _variant(extract=extract)))


def test_path_rule_rejected_in_html_spec(tmp_path: Path):
    extract = {"kind": "html", "rows": "article", "fields": {"section_id": {"path": "$.x"}}}
    with pytest.raises(SpecInvalid, match="path"):
        load_spec(_write(tmp_path, _variant(extract=extract)))


def test_value_rule_shorthand_depends_on_kind():
    assert value_rule("$.a", "json") == ValueRule(path="$.a")
    assert value_rule("li.x", "html") == ValueRule(css="li.x")
    assert value_rule({"const": "x"}, "json") == ValueRule(const="x")
    joined = value_rule({"join": ["$.a", "$.b"], "sep": "-"}, "json")
    assert joined == ValueRule(join=(ValueRule(path="$.a"), ValueRule(path="$.b")), sep="-")


def test_status_from_seats_and_modality_map_lowercased(tmp_path: Path):
    extract = {
        "kind": "json", "rows": "$.d[*]", "fields": {"section_id": "$.crn"},
        "status": {"from_seats": True},
        "modality": {"tokens": ["$.mode"], "map": {"Partially Online": "hybrid"}},
    }
    spec = load_spec(_write(tmp_path, _variant(extract=extract)))
    assert spec.extract.status is None and spec.extract.status_from_seats is True
    assert spec.extract.modality_map == {"partially online": "hybrid"}


def test_load_specs_from_directory(tmp_path: Path):
    _write(tmp_path, MINIMAL, "999.json")
    _write(tmp_path, _variant(cc_id=998), "998.json")
    specs = load_specs_from(tmp_path)
    assert sorted(specs) == [998, 999]


def test_load_specs_from_rejects_file_name_mismatch(tmp_path: Path):
    _write(tmp_path, MINIMAL, "1.json")
    with pytest.raises(SpecInvalid, match="file name"):
        load_specs_from(tmp_path)


def test_load_specs_from_empty_or_missing_directory_is_empty(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    assert load_specs_from(tmp_path / "empty") == {}
    assert load_specs_from(tmp_path / "missing") == {}
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_spec.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.schedule.replay.spec'`.

- [ ] **Step 4: Write the JSON schema**

Create `src/schedule/replay/schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Replay spec v1",
  "type": "object",
  "required": ["cc_id", "cc_name", "version", "recorded_at", "probe", "steps", "extract"],
  "additionalProperties": false,
  "properties": {
    "cc_id": {"type": "integer", "minimum": 1},
    "cc_name": {"type": "string", "minLength": 1},
    "version": {"const": 1},
    "recorded_at": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    "notes": {"type": "string"},
    "probe": {
      "type": "object",
      "required": ["course_code", "term"],
      "additionalProperties": false,
      "properties": {
        "course_code": {"type": "string", "minLength": 1},
        "term": {"type": "string", "pattern": "^(Spring|Summer|Fall) \\d{4}$"},
        "expect_min_rows": {"type": "integer", "minimum": 0}
      }
    },
    "inputs": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "term": {
          "type": "object",
          "required": ["format", "seasons"],
          "additionalProperties": false,
          "properties": {
            "format": {"type": "string", "minLength": 1},
            "seasons": {"$ref": "#/$defs/stringMap"}
          }
        },
        "named": {
          "type": "object",
          "propertyNames": {"pattern": "^[a-z][a-z0-9_]*$"},
          "additionalProperties": {
            "type": "object",
            "required": ["from"],
            "additionalProperties": false,
            "properties": {
              "from": {"enum": ["course_code", "subject", "number"]},
              "transform": {"enum": ["as_is", "upper", "dash_join", "compact"]}
            }
          }
        }
      }
    },
    "steps": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"$ref": "#/$defs/step"}},
    "extract": {"$ref": "#/$defs/extract"}
  },
  "$defs": {
    "stringMap": {"type": "object", "additionalProperties": {"type": "string"}},
    "valueRule": {
      "oneOf": [
        {"type": "string", "minLength": 1},
        {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "path": {"type": "string", "minLength": 1},
            "css": {"type": "string", "minLength": 1},
            "attr": {"type": "string", "minLength": 1},
            "regex": {"type": "string", "minLength": 1},
            "const": {"type": "string"},
            "join": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/valueRule"}},
            "sep": {"type": "string"}
          }
        }
      ]
    },
    "capture": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "cookie": {"type": "string", "minLength": 1},
        "regex": {"type": "string", "minLength": 1},
        "json": {"type": "string", "minLength": 1},
        "css": {"type": "string", "minLength": 1},
        "attr": {"type": "string", "minLength": 1},
        "lookup": {
          "type": "object",
          "required": ["rows", "label", "value"],
          "additionalProperties": false,
          "properties": {
            "rows": {"type": "string", "minLength": 1},
            "label": {"type": "string", "minLength": 1},
            "value": {"type": "string", "minLength": 1}
          }
        },
        "on_missing": {"enum": ["portal_changed", "term_not_listed"]}
      },
      "oneOf": [
        {"required": ["cookie"]},
        {"required": ["regex"]},
        {"required": ["json"]},
        {"required": ["css"]},
        {"required": ["lookup"]}
      ]
    },
    "paginate": {
      "type": "object",
      "required": ["param", "page_size", "total_capture"],
      "additionalProperties": false,
      "properties": {
        "param": {"type": "string", "minLength": 1},
        "first": {"type": "integer", "minimum": 0},
        "increment": {"type": "integer", "minimum": 1},
        "page_size": {"type": "integer", "minimum": 1},
        "max_pages": {"type": "integer", "minimum": 1, "maximum": 50},
        "total_capture": {"type": "string", "minLength": 1}
      }
    },
    "step": {
      "type": "object",
      "required": ["id", "method", "url"],
      "additionalProperties": false,
      "properties": {
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "method": {"enum": ["GET", "POST"]},
        "url": {"type": "string", "pattern": "^https://"},
        "query": {"$ref": "#/$defs/stringMap"},
        "form": {"$ref": "#/$defs/stringMap"},
        "json": {"type": "object"},
        "headers": {"$ref": "#/$defs/stringMap"},
        "captures": {
          "type": "object",
          "propertyNames": {"pattern": "^[a-z][a-z0-9_]*$"},
          "additionalProperties": {"$ref": "#/$defs/capture"}
        },
        "cache": {"type": "boolean"},
        "paginate": {"$ref": "#/$defs/paginate"}
      }
    },
    "filterRule": {
      "type": "object",
      "required": ["value"],
      "additionalProperties": false,
      "properties": {
        "value": {"$ref": "#/$defs/valueRule"},
        "equals": {"type": "string"},
        "any_of": {"type": "array", "minItems": 1, "items": {"type": "string"}}
      },
      "oneOf": [{"required": ["equals"]}, {"required": ["any_of"]}]
    },
    "meetingRule": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "each": {"type": "string", "minLength": 1},
        "days": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "flags": {"type": "array", "minItems": 7, "maxItems": 7, "items": {"$ref": "#/$defs/valueRule"}},
            "text": {"$ref": "#/$defs/valueRule"}
          },
          "oneOf": [{"required": ["flags"]}, {"required": ["text"]}]
        },
        "time_text": {"$ref": "#/$defs/valueRule"},
        "time_pattern": {"type": "string", "minLength": 1},
        "start": {"$ref": "#/$defs/valueRule"},
        "end": {"$ref": "#/$defs/valueRule"},
        "location": {"$ref": "#/$defs/valueRule"},
        "start_date": {"$ref": "#/$defs/valueRule"},
        "end_date": {"$ref": "#/$defs/valueRule"}
      }
    },
    "extract": {
      "type": "object",
      "required": ["kind", "rows", "fields"],
      "additionalProperties": false,
      "properties": {
        "kind": {"enum": ["json", "html"]},
        "rows": {"type": "string", "minLength": 1},
        "marker": {"type": "string", "minLength": 1},
        "filter": {"type": "array", "items": {"$ref": "#/$defs/filterRule"}},
        "fields": {
          "type": "object",
          "required": ["section_id"],
          "additionalProperties": false,
          "properties": {
            "section_id": {"$ref": "#/$defs/valueRule"},
            "title": {"$ref": "#/$defs/valueRule"},
            "instructor": {"$ref": "#/$defs/valueRule"},
            "seats_total": {"$ref": "#/$defs/valueRule"},
            "seats_used": {"$ref": "#/$defs/valueRule"},
            "seats_available": {"$ref": "#/$defs/valueRule"},
            "wait_capacity": {"$ref": "#/$defs/valueRule"},
            "course_code_as_listed": {"$ref": "#/$defs/valueRule"}
          }
        },
        "status": {
          "oneOf": [
            {"$ref": "#/$defs/valueRule"},
            {"type": "object", "required": ["from_seats"], "additionalProperties": false,
             "properties": {"from_seats": {"const": true}}}
          ]
        },
        "modality": {
          "type": "object",
          "additionalProperties": false,
          "properties": {
            "tokens": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/valueRule"}},
            "map": {"$ref": "#/$defs/stringMap"}
          }
        },
        "meetings": {"type": "array", "items": {"$ref": "#/$defs/meetingRule"}}
      }
    }
  }
}
```

- [ ] **Step 5: Write the spec model and loader**

Create `src/schedule/replay/spec.py`:

```python
"""Replay spec model: frozen dataclasses built from a schema-validated JSON file.

A spec is data recorded from a college's schedule portal: a short list of HTTP steps
plus an extraction block. ``load_spec`` validates the JSON against ``schema.json``,
converts it to dataclasses, then runs a few semantic checks the schema cannot express,
and raises ``SpecInvalid`` naming the file and field on any failure.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

import jsonschema
from jsonschema.exceptions import best_match

from ..errors import SpecInvalid

_SCHEMA_PATH = Path(__file__).parent / "schema.json"
_SCHEMA: dict = json.loads(_SCHEMA_PATH.read_text())
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

BUILTIN_PLACEHOLDERS: frozenset[str] = frozenset(
    {"course_code", "subject", "number", "term_label", "yyyy", "yy", "season", "Season"}
)
FIELD_NAMES: tuple[str, ...] = (
    "section_id",
    "title",
    "instructor",
    "seats_total",
    "seats_used",
    "seats_available",
    "wait_capacity",
    "course_code_as_listed",
)


def _empty_map() -> Mapping:
    return MappingProxyType({})


@dataclass(frozen=True)
class ValueRule:
    """Where one string comes from: a JSONPath (json rows) or a CSS selector (html rows),
    optionally an attribute instead of text, then optionally regex group 1; or a constant;
    or several rules joined with ``sep`` (empty parts dropped)."""

    path: str | None = None
    css: str | None = None
    attr: str | None = None
    regex: str | None = None
    const: str | None = None
    join: tuple["ValueRule", ...] = ()
    sep: str = " "


@dataclass(frozen=True)
class Capture:
    kind: str  # "cookie" | "regex" | "json" | "css" | "lookup"
    arg: str  # cookie name, regex pattern, JSONPath, CSS selector, or lookup rows path
    attr: str | None = None
    lookup_label: str | None = None
    lookup_value: str | None = None
    on_missing: str = "portal_changed"


@dataclass(frozen=True)
class Paginate:
    param: str
    total_capture: str
    page_size: int
    first: int = 0
    increment: int = 1
    max_pages: int = 10


@dataclass(frozen=True)
class Step:
    id: str
    method: str
    url: str
    query: Mapping[str, str] = field(default_factory=_empty_map)
    form: Mapping[str, str] = field(default_factory=_empty_map)
    json_body: Mapping[str, object] | None = None
    headers: Mapping[str, str] = field(default_factory=_empty_map)
    captures: Mapping[str, Capture] = field(default_factory=_empty_map)
    cache: bool = False
    paginate: Paginate | None = None


@dataclass(frozen=True)
class FilterRule:
    value: ValueRule
    equals: str | None = None
    any_of: tuple[str, ...] = ()


@dataclass(frozen=True)
class MeetingRule:
    each: str | None = None
    day_flags: tuple[ValueRule, ...] = ()
    day_text: ValueRule | None = None
    time_text: ValueRule | None = None
    time_pattern: str | None = None
    start: ValueRule | None = None
    end: ValueRule | None = None
    location: ValueRule | None = None
    start_date: ValueRule | None = None
    end_date: ValueRule | None = None


@dataclass(frozen=True)
class Extract:
    kind: str
    rows: str
    marker: str | None = None
    filters: tuple[FilterRule, ...] = ()
    fields: Mapping[str, ValueRule] = field(default_factory=_empty_map)
    status: ValueRule | None = None
    status_from_seats: bool = False
    modality_tokens: tuple[ValueRule, ...] = ()
    modality_map: Mapping[str, str] = field(default_factory=_empty_map)
    meetings: tuple[MeetingRule, ...] = ()


@dataclass(frozen=True)
class TermInput:
    format: str
    seasons: Mapping[str, str]


@dataclass(frozen=True)
class NamedInput:
    source: str  # "course_code" | "subject" | "number"
    transform: str  # "as_is" | "upper" | "dash_join" | "compact"


@dataclass(frozen=True)
class SpecInputs:
    term: TermInput | None = None
    named: Mapping[str, NamedInput] = field(default_factory=_empty_map)


@dataclass(frozen=True)
class Probe:
    course_code: str
    term: str
    expect_min_rows: int = 1


@dataclass(frozen=True)
class ReplaySpec:
    cc_id: int
    cc_name: str
    version: int
    recorded_at: str
    probe: Probe
    inputs: SpecInputs
    steps: tuple[Step, ...]
    extract: Extract
    source_path: str = ""


# --- loading -------------------------------------------------------------------------


def load_spec(path: Path) -> ReplaySpec:
    """Read, schema-validate, build, and semantically check one spec file."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecInvalid(f"{path}: cannot read spec: {exc}") from exc
    error = best_match(jsonschema.Draft202012Validator(_SCHEMA).iter_errors(raw))
    if error is not None:
        raise SpecInvalid(f"{path}: {error.json_path}: {error.message}")
    spec = _build(raw, str(path))
    _check_semantics(spec)
    return spec


def value_rule(raw: object, kind: str) -> ValueRule:
    """A bare string is a JSONPath for json specs and a CSS selector for html specs."""
    if isinstance(raw, str):
        return ValueRule(path=raw) if kind == "json" else ValueRule(css=raw)
    if not isinstance(raw, dict):
        raise SpecInvalid(f"value rule must be a string or object, got {raw!r}")
    return ValueRule(
        path=raw.get("path"),
        css=raw.get("css"),
        attr=raw.get("attr"),
        regex=raw.get("regex"),
        const=raw.get("const"),
        join=tuple(value_rule(part, kind) for part in raw.get("join", [])),
        sep=raw.get("sep", " "),
    )


def _build(raw: dict, source_path: str) -> ReplaySpec:
    kind = raw["extract"]["kind"]
    probe = raw["probe"]
    return ReplaySpec(
        cc_id=raw["cc_id"],
        cc_name=raw["cc_name"],
        version=raw["version"],
        recorded_at=raw["recorded_at"],
        probe=Probe(
            course_code=probe["course_code"],
            term=probe["term"],
            expect_min_rows=probe.get("expect_min_rows", 1),
        ),
        inputs=_inputs(raw.get("inputs", {})),
        steps=tuple(_step(s) for s in raw["steps"]),
        extract=_extract(raw["extract"], kind),
        source_path=source_path,
    )


def _inputs(raw: dict) -> SpecInputs:
    term = raw.get("term")
    named = {
        name: NamedInput(source=entry["from"], transform=entry.get("transform", "as_is"))
        for name, entry in raw.get("named", {}).items()
    }
    return SpecInputs(
        term=TermInput(format=term["format"], seasons=MappingProxyType(dict(term["seasons"])))
        if term
        else None,
        named=MappingProxyType(named),
    )


def _capture(raw: dict) -> Capture:
    on_missing = raw.get("on_missing", "portal_changed")
    for kind in ("cookie", "regex", "json", "css"):
        if kind in raw:
            return Capture(kind=kind, arg=raw[kind], attr=raw.get("attr"), on_missing=on_missing)
    lookup = raw["lookup"]
    return Capture(
        kind="lookup",
        arg=lookup["rows"],
        lookup_label=lookup["label"],
        lookup_value=lookup["value"],
        on_missing=on_missing,
    )


def _paginate(raw: dict | None) -> Paginate | None:
    if raw is None:
        return None
    return Paginate(
        param=raw["param"],
        total_capture=raw["total_capture"],
        page_size=raw["page_size"],
        first=raw.get("first", 0),
        increment=raw.get("increment", 1),
        max_pages=raw.get("max_pages", 10),
    )


def _step(raw: dict) -> Step:
    return Step(
        id=raw["id"],
        method=raw["method"],
        url=raw["url"],
        query=MappingProxyType(dict(raw.get("query", {}))),
        form=MappingProxyType(dict(raw.get("form", {}))),
        json_body=MappingProxyType(dict(raw["json"])) if "json" in raw else None,
        headers=MappingProxyType(dict(raw.get("headers", {}))),
        captures=MappingProxyType({n: _capture(c) for n, c in raw.get("captures", {}).items()}),
        cache=raw.get("cache", False),
        paginate=_paginate(raw.get("paginate")),
    )


def _opt_rule(raw: dict, key: str, kind: str) -> ValueRule | None:
    return value_rule(raw[key], kind) if key in raw else None


def _meeting(raw: dict, kind: str) -> MeetingRule:
    days = raw.get("days", {})
    return MeetingRule(
        each=raw.get("each"),
        day_flags=tuple(value_rule(r, kind) for r in days.get("flags", [])),
        day_text=value_rule(days["text"], kind) if "text" in days else None,
        time_text=_opt_rule(raw, "time_text", kind),
        time_pattern=raw.get("time_pattern"),
        start=_opt_rule(raw, "start", kind),
        end=_opt_rule(raw, "end", kind),
        location=_opt_rule(raw, "location", kind),
        start_date=_opt_rule(raw, "start_date", kind),
        end_date=_opt_rule(raw, "end_date", kind),
    )


def _extract(raw: dict, kind: str) -> Extract:
    status = raw.get("status")
    from_seats = isinstance(status, dict) and status.get("from_seats") is True
    modality = raw.get("modality", {})
    return Extract(
        kind=kind,
        rows=raw["rows"],
        marker=raw.get("marker"),
        filters=tuple(
            FilterRule(
                value=value_rule(f["value"], kind),
                equals=f.get("equals"),
                any_of=tuple(f.get("any_of", ())),
            )
            for f in raw.get("filter", [])
        ),
        fields=MappingProxyType({n: value_rule(r, kind) for n, r in raw["fields"].items()}),
        status=None if status is None or from_seats else value_rule(status, kind),
        status_from_seats=from_seats,
        modality_tokens=tuple(value_rule(t, kind) for t in modality.get("tokens", [])),
        modality_map=MappingProxyType({k.lower(): v for k, v in modality.get("map", {}).items()}),
        meetings=tuple(_meeting(m, kind) for m in raw.get("meetings", [])),
    )


# --- semantic checks ------------------------------------------------------------------


def _check_semantics(spec: ReplaySpec) -> None:
    where = spec.source_path
    if spec.extract.kind == "json" and not spec.extract.rows.endswith("[*]"):
        raise SpecInvalid(f"{where}: extract.rows must end with [*] for kind=json")
    for step in spec.steps[:-1]:
        if step.paginate is not None:
            raise SpecInvalid(f"{where}: step {step.id!r}: paginate is only allowed on the last step")
    last = spec.steps[-1]
    if last.paginate is not None and last.paginate.total_capture not in last.captures:
        raise SpecInvalid(
            f"{where}: paginate.total_capture {last.paginate.total_capture!r} "
            f"is not a capture of step {last.id!r}"
        )
    _check_placeholders(spec)
    _check_rule_kinds(spec)


def _placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(text))


def _step_templates(step: Step) -> list[str]:
    templates = [step.url, *step.query.values(), *step.form.values(), *step.headers.values()]
    templates.extend(_string_leaves(step.json_body or {}))
    templates.extend(c.arg for c in step.captures.values() if c.kind == "regex")
    return templates


def _string_leaves(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [leaf for v in value.values() for leaf in _string_leaves(v)]
    if isinstance(value, (list, tuple)):
        return [leaf for v in value for leaf in _string_leaves(v)]
    return []


def _check_placeholders(spec: ReplaySpec) -> None:
    known = set(BUILTIN_PLACEHOLDERS) | set(spec.inputs.named)
    if spec.inputs.term is not None:
        known.add("term")
        _require_known(spec, spec.inputs.term.format, known - {"term"} | {"SEASON"}, "inputs.term.format")
    for step in spec.steps:
        for template in _step_templates(step):
            _require_known(spec, template, known, f"step {step.id!r}")
        known = known | set(step.captures)
    for index, rule in enumerate(spec.extract.filters):
        for template in ([rule.equals] if rule.equals is not None else list(rule.any_of)):
            _require_known(spec, template, known, f"extract.filter[{index}]")


def _require_known(spec: ReplaySpec, template: str, known: set[str], where: str) -> None:
    unknown = _placeholders(template) - known
    if unknown:
        names = ", ".join(sorted(unknown))
        raise SpecInvalid(f"{spec.source_path}: {where}: unknown placeholder(s) {names}")


def _walk_rules(extract: Extract) -> Iterator[ValueRule]:
    yield from extract.fields.values()
    yield from (f.value for f in extract.filters)
    if extract.status is not None:
        yield extract.status
    yield from extract.modality_tokens
    for meeting in extract.meetings:
        yield from meeting.day_flags
        for rule in (
            meeting.day_text, meeting.time_text, meeting.start, meeting.end,
            meeting.location, meeting.start_date, meeting.end_date,
        ):
            if rule is not None:
                yield rule


def _flatten(rule: ValueRule) -> Iterator[ValueRule]:
    yield rule
    for part in rule.join:
        yield from _flatten(part)


def _check_rule_kinds(spec: ReplaySpec) -> None:
    kind = spec.extract.kind
    for top in _walk_rules(spec.extract):
        for rule in _flatten(top):
            sources = [s for s in ("path", "css", "const", "join") if getattr(rule, s)]
            if len(sources) != 1:
                raise SpecInvalid(
                    f"{spec.source_path}: value rule needs exactly one of path/css/const/join: {rule}"
                )
            if kind == "json" and (rule.css or rule.attr):
                raise SpecInvalid(f"{spec.source_path}: css/attr rules are not allowed in a json spec")
            if kind == "html" and rule.path:
                raise SpecInvalid(f"{spec.source_path}: path rules are not allowed in an html spec")
    if kind == "json" and spec.extract.marker:
        raise SpecInvalid(f"{spec.source_path}: extract.marker is only for html specs")
```

- [ ] **Step 6: Write the registry**

Create `src/schedule/replay/registry.py`:

```python
"""Loads every replay spec under ``src/schedule/data/specs`` once and serves them by cc_id.

Loading fails fast: one invalid file raises ``SpecInvalid`` naming it, so a bad spec is
caught by the test suite (tests/schedule/replay/test_specs_registry.py) rather than at
query time.
"""
from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from ..errors import SpecInvalid
from .spec import ReplaySpec, load_spec

SPECS_DIR = Path(__file__).parent.parent / "data" / "specs"


def load_specs_from(directory: Path) -> Mapping[int, ReplaySpec]:
    """Every ``<cc_id>.json`` in ``directory``, keyed by cc_id. Empty when none exist."""
    specs: dict[int, ReplaySpec] = {}
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        spec = load_spec(path)
        if path.stem != str(spec.cc_id):
            raise SpecInvalid(f"{path}: file name must be <cc_id>.json, got cc_id={spec.cc_id}")
        if spec.cc_id in specs:
            raise SpecInvalid(f"{path}: duplicate cc_id {spec.cc_id}")
        specs[spec.cc_id] = spec
    return MappingProxyType(specs)


@lru_cache(maxsize=1)
def load_all_specs() -> Mapping[int, ReplaySpec]:
    return load_specs_from(SPECS_DIR)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_spec.py -q`
Expected: all PASS.

- [ ] **Step 8: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add pyproject.toml uv.lock src/schedule/replay/schema.json src/schedule/replay/spec.py src/schedule/replay/registry.py tests/schedule/replay/test_spec.py
git commit -m "feat(schedule): add replay spec model, JSON schema, loader, and registry"
```

---

### Task 3: Placeholder inputs and templating

**Files:**
- Create: `src/schedule/replay/inputs.py`
- Test: `tests/schedule/replay/test_inputs.py`

**Interfaces:**
- Consumes: `spec.SpecInputs`, `spec.TermInput`, `spec.NamedInput` (Task 2); `term.ParsedTerm`, `term.TermNotListedError`.
- Produces: `inputs.build_values(spec_inputs: SpecInputs, term: ParsedTerm, course_code: str) -> Mapping[str, str]`, `inputs.render(template: str, values: Mapping[str, str]) -> str`, `inputs.course_parts(course_code: str) -> tuple[str, str]`, `inputs.MissingPlaceholder(KeyError)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/schedule/replay/test_inputs.py`:

```python
from __future__ import annotations

from types import MappingProxyType

import pytest

from src.schedule.replay.inputs import MissingPlaceholder, build_values, course_parts, render
from src.schedule.replay.spec import NamedInput, SpecInputs, TermInput
from src.schedule.term import TermNotListedError, parse_term_label

_FALL = parse_term_label("Fall 2026")


@pytest.mark.parametrize(
    "code,expected",
    [
        ("MATH 150AC", ("MATH", "150AC")),
        ("MATH-C2220", ("MATH", "C2220")),
        ("mat 1b", ("MAT", "1B")),
        ("CIS 17A", ("CIS", "17A")),
        ("ENGWR300", ("ENGWR", "300")),
        ("weird code 1 2", ("WEIRD CODE 1 2", "")),
    ],
)
def test_course_parts(code, expected):
    assert course_parts(code) == expected


def test_builtin_values():
    values = build_values(SpecInputs(), _FALL, "MAT 1B")
    assert values["course_code"] == "MAT 1B"
    assert values["subject"] == "MAT"
    assert values["number"] == "1B"
    assert values["term_label"] == "Fall 2026"
    assert values["yyyy"] == "2026"
    assert values["yy"] == "26"
    assert values["season"] == "fall"
    assert values["Season"] == "Fall"
    assert "term" not in values


def test_term_input_renders_format_with_season_code():
    inputs = SpecInputs(term=TermInput(format="{yy}{SEASON}", seasons=MappingProxyType({"fall": "FAL"})))
    assert build_values(inputs, _FALL, "MAT 1B")["term"] == "26FAL"


def test_term_input_season_missing_is_term_not_listed():
    inputs = SpecInputs(term=TermInput(format="{yy}{SEASON}", seasons=MappingProxyType({"spring": "SPR"})))
    with pytest.raises(TermNotListedError, match="Fall 2026"):
        build_values(inputs, _FALL, "MAT 1B")


@pytest.mark.parametrize(
    "course_code,source,transform,expected",
    [
        ("MAT 1B", "course_code", "as_is", "MAT 1B"),
        ("mat 1b", "course_code", "upper", "MAT 1B"),
        ("MAT 1B", "course_code", "dash_join", "MAT-1B"),
        ("MATH-C2220", "course_code", "dash_join", "MATH-C2220"),
        ("MAT 1B", "course_code", "compact", "MAT1B"),
        ("MAT 1B", "subject", "as_is", "MAT"),
        ("MAT 1B", "number", "as_is", "1B"),
    ],
)
def test_named_inputs(course_code, source, transform, expected):
    inputs = SpecInputs(named=MappingProxyType({"x": NamedInput(source=source, transform=transform)}))
    assert build_values(inputs, _FALL, course_code)["x"] == expected


def test_values_are_read_only():
    values = build_values(SpecInputs(), _FALL, "MAT 1B")
    with pytest.raises(TypeError):
        values["subject"] = "X"  # type: ignore[index]


def test_render_substitutes_and_leaves_regex_braces():
    values = {"term": "26FAL", "term_label": "Fall 2026"}
    assert render("Term eq '{term}'", values) == "Term eq '26FAL'"
    assert render(r'for="(\d{4})">\s*{term_label}', values) == r'for="(\d{4})">\s*Fall 2026'


def test_render_missing_placeholder_raises():
    with pytest.raises(MissingPlaceholder, match="token"):
        render("x={token}", {})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_inputs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.schedule.replay.inputs'`.

- [ ] **Step 3: Implement inputs**

Create `src/schedule/replay/inputs.py`:

```python
"""Placeholder values for a replay run, and the ``{name}`` template renderer.

Built-in placeholders come from the term and course code. ``inputs.term`` adds ``{term}``
from a format string; named inputs add derived course-code spellings. Captures add
their own names at run time (see executor.py).
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from types import MappingProxyType

from ..term import ParsedTerm, TermNotListedError
from .spec import SpecInputs

_COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]+)\s*[- ]?\s*([A-Za-z0-9]+)\s*$")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingPlaceholder(KeyError):
    """A template names a placeholder that has no value (a spec bug; caught at load)."""


def course_parts(course_code: str) -> tuple[str, str]:
    """('MATH', '150AC') for 'MATH 150AC'. Unparseable codes become (code upper, '')."""
    match = _COURSE_CODE_RE.match(course_code)
    if match is None:
        return course_code.strip().upper(), ""
    return match.group(1).upper(), match.group(2).upper()


def _as_is(subject: str, number: str, course_code: str) -> str:
    return course_code


def _upper(subject: str, number: str, course_code: str) -> str:
    return course_code.upper()


def _dash_join(subject: str, number: str, course_code: str) -> str:
    return f"{subject}-{number}" if number else subject


def _compact(subject: str, number: str, course_code: str) -> str:
    return f"{subject}{number}"


_TRANSFORMS: Mapping[str, Callable[[str, str, str], str]] = MappingProxyType(
    {"as_is": _as_is, "upper": _upper, "dash_join": _dash_join, "compact": _compact}
)
_SOURCES: Mapping[str, Callable[[str, str, str], str]] = MappingProxyType(
    {
        "course_code": lambda subject, number, code: code,
        "subject": lambda subject, number, code: subject,
        "number": lambda subject, number, code: number,
    }
)


def build_values(spec_inputs: SpecInputs, term: ParsedTerm, course_code: str) -> Mapping[str, str]:
    """Every placeholder a spec may use before any capture has run."""
    code = course_code.strip()
    subject, number = course_parts(code)
    values: dict[str, str] = {
        "course_code": code,
        "subject": subject,
        "number": number,
        "term_label": term.label,
        "yyyy": str(term.year),
        "yy": f"{term.year % 100:02d}",
        "season": term.season,
        "Season": term.season.capitalize(),
    }
    if spec_inputs.term is not None:
        season_code = spec_inputs.term.seasons.get(term.season)
        if season_code is None:
            raise TermNotListedError(
                f"{term.label!r}: this spec has no term code for {term.season} terms"
            )
        values["term"] = render(spec_inputs.term.format, {**values, "SEASON": season_code})
    for name, named in spec_inputs.named.items():
        source_value = _SOURCES[named.source](subject, number, code)
        values[name] = _TRANSFORMS[named.transform](subject, number, source_value)
    return MappingProxyType(values)


def render(template: str, values: Mapping[str, str]) -> str:
    """Replace every ``{name}`` with its value. Regex quantifiers like ``{4}`` are left
    alone because they do not start with a letter."""

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise MissingPlaceholder(name)
        return values[name]

    return _PLACEHOLDER_RE.sub(substitute, template)
```

Note on `_dash_join` with `from: subject` or `from: number`: the transform receives the source value as the third argument, so `dash_join` only makes sense with `from: course_code`. That is the only combination the specs in this plan use.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_inputs.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add src/schedule/replay/inputs.py tests/schedule/replay/test_inputs.py
git commit -m "feat(schedule): add replay placeholder inputs and template rendering"
```

---

### Task 4: Captures

**Files:**
- Create: `src/schedule/replay/captures.py`
- Modify: `pyproject.toml` (add `beautifulsoup4`, `soupsieve`)
- Test: `tests/schedule/replay/test_captures.py`

**Interfaces:**
- Consumes: `spec.Capture` (Task 2), `inputs.render` (Task 3), `jsonpath.resolve` / `first` (Task 1), `term.term_match_rank`, `errors.PortalChanged`.
- Produces: `captures.evaluate_capture(*, name: str, capture: Capture, step_id: str, response_text: str, cookies: Mapping[str, str], term: ParsedTerm, values: Mapping[str, str]) -> str`.

- [ ] **Step 1: Add the dependencies**

Run: `uv add "beautifulsoup4>=4.12.3" "soupsieve>=2.5"`
Expected: both appear under `dependencies` in `pyproject.toml`; `uv.lock` updates.

- [ ] **Step 2: Write the failing tests**

Create `tests/schedule/replay/test_captures.py`:

```python
from __future__ import annotations

import json

import pytest

from src.schedule.errors import PortalChanged
from src.schedule.replay.captures import evaluate_capture
from src.schedule.replay.spec import Capture
from src.schedule.term import TermNotListedError, parse_term_label

_FALL = parse_term_label("Fall 2026")
_VALUES = {"term_label": "Fall 2026"}


def _eval(capture: Capture, text: str = "", cookies: dict | None = None, term=_FALL) -> str:
    return evaluate_capture(
        name="x", capture=capture, step_id="s", response_text=text,
        cookies=cookies or {}, term=term, values=_VALUES,
    )


def test_cookie_capture():
    assert _eval(Capture(kind="cookie", arg="XSRF-TOKEN"), cookies={"XSRF-TOKEN": "abc"}) == "abc"


def test_cookie_missing_is_portal_changed():
    with pytest.raises(PortalChanged, match="cookie"):
        _eval(Capture(kind="cookie", arg="XSRF-TOKEN"), cookies={})


def test_regex_capture_uses_group_one_and_placeholders():
    html = '<label for="1269">Fall 2026</label><label for="1273">Spring 2027</label>'
    capture = Capture(kind="regex", arg=r'for="(\d+)">\s*{term_label}\b')
    assert _eval(capture, text=html) == "1269"


def test_regex_capture_without_group_returns_whole_match():
    assert _eval(Capture(kind="regex", arg=r"\d{4}"), text="strm 1269 ok") == "1269"


def test_regex_missing_term_not_listed_when_configured():
    capture = Capture(kind="regex", arg=r'for="(\d+)">\s*{term_label}', on_missing="term_not_listed")
    with pytest.raises(TermNotListedError, match="Fall 2026"):
        _eval(capture, text="<p>nothing here</p>")


def test_json_capture_stringifies_first_match():
    text = json.dumps({"terms": [{"code": 202610}, {"code": 202620}]})
    assert _eval(Capture(kind="json", arg="$.terms[*].code"), text=text) == "202610"


def test_json_capture_not_json_is_portal_changed():
    with pytest.raises(PortalChanged, match="JSON"):
        _eval(Capture(kind="json", arg="$.x"), text="<html>")


def test_css_capture_text_and_attr():
    html = "<div><span id='totalResults' style='x'>  15 </span><a class='n' href='/next'>n</a></div>"
    assert _eval(Capture(kind="css", arg="#totalResults"), text=html) == "15"
    assert _eval(Capture(kind="css", arg="a.n", attr="href"), text=html) == "/next"


def test_css_missing_is_portal_changed():
    with pytest.raises(PortalChanged, match="css"):
        _eval(Capture(kind="css", arg="#nope"), text="<p>x</p>")


_TERMS = json.dumps([
    {"termCode": "202620", "termDesc": "Winter/Spring 2027"},
    {"termCode": "202615", "termDesc": "NOCE Fall 2026"},
    {"termCode": "202610", "termDesc": "Fall 2026"},
])


def _lookup(on_missing="portal_changed") -> Capture:
    return Capture(kind="lookup", arg="$[*]", lookup_label="$.termDesc",
                   lookup_value="$.termCode", on_missing=on_missing)


def test_lookup_prefers_exact_label_over_substring():
    assert _eval(_lookup(), text=_TERMS) == "202610"


def test_lookup_falls_back_to_season_and_year_tokens():
    assert _eval(_lookup(), text=_TERMS, term=parse_term_label("Spring 2027")) == "202620"


def test_lookup_missing_term_not_listed():
    with pytest.raises(TermNotListedError, match="Summer 2027"):
        _eval(_lookup("term_not_listed"), text=_TERMS, term=parse_term_label("Summer 2027"))
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_captures.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.schedule.replay.captures'`.

- [ ] **Step 4: Implement captures**

Create `src/schedule/replay/captures.py`:

```python
"""Pull one named value out of a step's response for use as a placeholder later.

Kinds: ``cookie`` (from the session jar), ``regex`` (group 1 over the body, placeholders
rendered first), ``json`` (first JSONPath match), ``css`` (first element's text or an
attribute) and ``lookup`` (the row whose label best matches the requested term, by
``term_match_rank``). A capture that finds nothing raises ``PortalChanged``, or
``TermNotListedError`` when ``on_missing`` says so.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from bs4 import BeautifulSoup

from ..errors import PortalChanged
from ..term import ParsedTerm, TermNotListedError, term_match_rank
from .inputs import render
from .jsonpath import first, resolve
from .spec import Capture


def evaluate_capture(
    *,
    name: str,
    capture: Capture,
    step_id: str,
    response_text: str,
    cookies: Mapping[str, str],
    term: ParsedTerm,
    values: Mapping[str, str],
) -> str:
    if capture.kind == "cookie":
        found = cookies.get(capture.arg)
    elif capture.kind == "regex":
        found = _regex(render(capture.arg, values), response_text)
    elif capture.kind == "json":
        found = _stringify(first(_json(response_text, step_id), capture.arg))
    elif capture.kind == "css":
        found = _css(capture, response_text)
    else:
        found = _lookup(capture, _json(response_text, step_id), term)
    if found is None or found == "":
        _raise_missing(name, capture, step_id, term)
    return str(found)


def _raise_missing(name: str, capture: Capture, step_id: str, term: ParsedTerm) -> None:
    if capture.on_missing == "term_not_listed":
        raise TermNotListedError(
            f"Term {term.label!r} not found by capture {name!r} in step {step_id!r}"
        )
    raise PortalChanged(
        f"capture {name!r} ({capture.kind} {capture.arg!r}) found nothing in step {step_id!r}"
    )


def _json(text: str, step_id: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise PortalChanged(f"step {step_id!r} response is not JSON: {exc}") from exc


def _regex(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.DOTALL)
    if match is None:
        return None
    return match.group(1) if match.groups() else match.group(0)


def _css(capture: Capture, text: str) -> str | None:
    element = BeautifulSoup(text, "html.parser").select_one(capture.arg)
    if element is None:
        return None
    if capture.attr:
        value = element.get(capture.attr)
        return str(value) if value is not None else None
    return " ".join(element.get_text(" ").split())


def _lookup(capture: Capture, doc: Any, term: ParsedTerm) -> str | None:
    best: tuple[int, str] | None = None
    for row in resolve(doc, capture.arg):
        label = _stringify(first(row, capture.lookup_label or "$"))
        rank = term_match_rank(term, label) if label else None
        if rank is None:
            continue
        value = _stringify(first(row, capture.lookup_value or "$"))
        if value and (best is None or rank < best[0]):
            best = (rank, value)
    return best[1] if best else None


def _stringify(value: Any) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_captures.py -q`
Expected: all PASS.

- [ ] **Step 6: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add pyproject.toml uv.lock src/schedule/replay/captures.py tests/schedule/replay/test_captures.py
git commit -m "feat(schedule): add replay response captures (cookie, regex, json, css, term lookup)"
```

---

### Task 5: Executor (steps, cache, pagination, throttle, retry)

**Files:**
- Create: `src/schedule/replay/executor.py`
- Create: `tests/schedule/replay/fakes.py`
- Test: `tests/schedule/replay/test_executor.py`

**Interfaces:**
- Consumes: `spec.ReplaySpec`, `spec.Step`, `spec.Paginate` (Task 2); `inputs.render` (Task 3); `captures.evaluate_capture` (Task 4); `errors.PortalChanged`.
- Produces: `executor.ExecutionResult(bodies: tuple[str, ...], captures: Mapping[str, str], final_url: str)`, `executor.HostThrottle(min_interval, *, clock, sleeper).wait(url)`, `executor.ReplayExecutor(session=None, *, throttle=None, sleeper=time.sleep).execute(spec, *, term, values) -> ExecutionResult`, constants `executor.REQUEST_TIMEOUT_SECONDS = 20`, `executor.MIN_INTERVAL_PER_HOST = 0.5`, `executor.USER_AGENT`.
- Produces for tests: `fakes.FakeResponse(text, status, url, cookies)`, `fakes.FakeSession(routes)` whose `.request(method, url, *, params, data, json, headers, timeout)` routes by URL prefix and records `.calls`.

- [ ] **Step 1: Write the test fakes**

Create `tests/schedule/replay/fakes.py`:

```python
"""Offline stand-ins for requests.Session used by the replay tests."""
from __future__ import annotations

from collections.abc import Iterator

import requests


class FakeResponse:
    def __init__(self, text: str = "", status: int = 200, url: str = "",
                 cookies: dict[str, str] | None = None) -> None:
        self.text = text
        self.status_code = status
        self.url = url
        self.cookies = cookies or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} for {self.url}")


class FakeSession:
    """Routes requests by URL prefix.

    A route value is a body string, a FakeResponse, an Exception instance to raise, or a
    list of those consumed in order (one per call). Every call is appended to ``calls``
    as a dict with method, url, params, data, json and headers. Cookies set on a
    FakeResponse are copied into ``cookies`` so cookie captures can read them.
    """

    def __init__(self, routes: dict[str, object]) -> None:
        self._routes: dict[str, object] = {
            prefix: iter(route) if isinstance(route, list) else route
            for prefix, route in routes.items()
        }
        self.calls: list[dict[str, object]] = []
        self.cookies: dict[str, str] = {}
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, *, params=None, data=None, json=None,
                headers=None, timeout=None) -> FakeResponse:
        self.calls.append({
            "method": method, "url": url, "params": dict(params or {}),
            "data": dict(data or {}), "json": json, "headers": dict(headers or {}),
        })
        for prefix, route in self._routes.items():
            if url.startswith(prefix):
                return self._respond(route, url)
        raise AssertionError(f"FakeSession has no route for {url}")

    def _respond(self, route: object, url: str) -> FakeResponse:
        if isinstance(route, Iterator):
            route = next(route)
        if isinstance(route, Exception):
            raise route
        response = route if isinstance(route, FakeResponse) else FakeResponse(text=str(route))
        if not response.url:
            response = FakeResponse(text=response.text, status=response.status_code, url=url,
                                    cookies=response.cookies)
        self.cookies = {**self.cookies, **response.cookies}
        response.raise_for_status()
        return response
```

- [ ] **Step 2: Write the failing executor tests**

Create `tests/schedule/replay/test_executor.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from src.schedule.errors import PortalChanged
from src.schedule.replay.executor import ExecutionResult, HostThrottle, ReplayExecutor
from src.schedule.replay.inputs import build_values
from src.schedule.replay.spec import load_spec
from src.schedule.term import parse_term_label

from .fakes import FakeResponse, FakeSession

_FALL = parse_term_label("Fall 2026")


def _spec(tmp_path: Path, steps: list[dict], inputs: dict | None = None):
    data = {
        "cc_id": 999, "cc_name": "Test", "version": 1, "recorded_at": "2026-09-23",
        "probe": {"course_code": "MATH 1", "term": "Fall 2026"},
        "inputs": inputs if inputs is not None else {
            "term": {"format": "{yy}{SEASON}", "seasons": {"fall": "FAL"}}},
        "steps": steps,
        "extract": {"kind": "json", "rows": "$.rows[*]", "fields": {"section_id": "$.id"}},
    }
    path = tmp_path / "999.json"
    path.write_text(json.dumps(data))
    return load_spec(path)


def _executor(session: FakeSession, sleeper=None) -> ReplayExecutor:
    return ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=sleeper or (lambda s: None))


def _run(executor: ReplayExecutor, spec) -> ExecutionResult:
    return executor.execute(spec, term=_FALL, values=build_values(spec.inputs, _FALL, "MATH 1"))


def test_single_get_renders_url_query_and_headers(tmp_path):
    spec = _spec(tmp_path, [{
        "id": "search", "method": "GET", "url": "https://example.edu/api/{term}",
        "query": {"subj": "{subject}", "num": "{number}"}, "headers": {"Accept": "application/json"},
    }])
    session = FakeSession({"https://example.edu/api/26FAL": '{"rows": []}'})
    result = _run(_executor(session), spec)
    assert result.bodies == ('{"rows": []}',)
    assert result.final_url == "https://example.edu/api/26FAL"
    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["params"] == {"subj": "MATH", "num": "1"}
    assert call["headers"] == {"Accept": "application/json"}


def test_post_form_and_json_bodies_are_rendered(tmp_path):
    spec = _spec(tmp_path, [{
        "id": "s", "method": "POST", "url": "https://example.edu/api",
        "form": {"term": "{term}"}, "json": {"q": {"keyword": "{subject} {number}"}},
    }])
    session = FakeSession({"https://example.edu/api": "{}"})
    _run(_executor(session), spec)
    assert session.calls[0]["data"] == {"term": "26FAL"}
    assert session.calls[0]["json"] == {"q": {"keyword": "MATH 1"}}


def test_captures_flow_into_later_steps(tmp_path):
    spec = _spec(tmp_path, [
        {"id": "boot", "method": "GET", "url": "https://example.edu/",
         "captures": {"tok": {"regex": 'name="tok" value="([^"]+)"'}, "sid": {"cookie": "SID"}}},
        {"id": "search", "method": "POST", "url": "https://example.edu/api",
         "form": {"tok": "{tok}", "sid": "{sid}"}},
    ])
    session = FakeSession({
        "https://example.edu/api": "{}",
        "https://example.edu/": FakeResponse(text='<input name="tok" value="T1">', cookies={"SID": "S9"}),
    })
    result = _run(_executor(session), spec)
    assert result.captures == {"tok": "T1", "sid": "S9"}
    assert session.calls[1]["data"] == {"tok": "T1", "sid": "S9"}
    assert result.bodies == ("{}",)


def test_cached_step_is_requested_once_per_executor(tmp_path):
    spec = _spec(tmp_path, [
        {"id": "terms", "method": "GET", "url": "https://example.edu/terms.json", "cache": True,
         "captures": {"term": {"json": "$[0].code"}}},
        {"id": "search", "method": "GET", "url": "https://example.edu/{term}/sections.json", "cache": True},
    ], inputs={})
    session = FakeSession({
        "https://example.edu/terms.json": '[{"code": "202610"}]',
        "https://example.edu/202610/sections.json": '{"rows": []}',
    })
    executor = _executor(session)
    _run(executor, spec)
    _run(executor, spec)
    assert [c["url"] for c in session.calls] == [
        "https://example.edu/terms.json", "https://example.edu/202610/sections.json"]


def test_uncached_step_is_requested_every_run(tmp_path):
    spec = _spec(tmp_path, [{"id": "s", "method": "GET", "url": "https://example.edu/api"}])
    session = FakeSession({"https://example.edu/api": "{}"})
    executor = _executor(session)
    _run(executor, spec)
    _run(executor, spec)
    assert len(session.calls) == 2


def test_retries_once_on_connection_error(tmp_path):
    spec = _spec(tmp_path, [{"id": "s", "method": "GET", "url": "https://example.edu/api"}])
    session = FakeSession({"https://example.edu/api": [requests.ConnectionError("reset"), "{}"]})
    slept: list[float] = []
    result = _run(_executor(session, sleeper=slept.append), spec)
    assert result.bodies == ("{}",)
    assert len(session.calls) == 2
    assert slept == [1.0]


def test_second_connection_error_propagates(tmp_path):
    spec = _spec(tmp_path, [{"id": "s", "method": "GET", "url": "https://example.edu/api"}])
    session = FakeSession({"https://example.edu/api": [
        requests.ConnectionError("a"), requests.ConnectionError("b")]})
    with pytest.raises(requests.ConnectionError, match="b"):
        _run(_executor(session), spec)


def test_http_error_propagates_without_retry(tmp_path):
    spec = _spec(tmp_path, [{"id": "s", "method": "GET", "url": "https://example.edu/api"}])
    session = FakeSession({"https://example.edu/api": FakeResponse(text="", status=500)})
    with pytest.raises(requests.HTTPError):
        _run(_executor(session), spec)
    assert len(session.calls) == 1


def _paged_spec(tmp_path, total_text: str, max_pages: int = 10):
    return _spec(tmp_path, [{
        "id": "search", "method": "GET", "url": "https://example.edu/search",
        "query": {"q": "{subject}", "offset": "0"},
        "captures": {"total": {"css": "#total"}},
        "paginate": {"param": "offset", "first": 0, "increment": 1, "page_size": 20,
                     "max_pages": max_pages, "total_capture": "total"},
    }]), f"<div><span id='total'>{total_text}</span></div>"


def test_paginate_requests_ceil_total_over_page_size_pages(tmp_path):
    spec, page = _paged_spec(tmp_path, "45")
    session = FakeSession({"https://example.edu/search": page})
    result = _run(_executor(session), spec)
    assert len(result.bodies) == 3
    assert [c["params"]["offset"] for c in session.calls] == ["0", "1", "2"]


def test_paginate_single_page_when_total_fits(tmp_path):
    spec, page = _paged_spec(tmp_path, "15")
    session = FakeSession({"https://example.edu/search": page})
    result = _run(_executor(session), spec)
    assert len(result.bodies) == 1


def test_paginate_zero_total_is_one_page(tmp_path):
    spec, page = _paged_spec(tmp_path, "0")
    session = FakeSession({"https://example.edu/search": page})
    assert len(_run(_executor(session), spec).bodies) == 1


def test_paginate_is_capped_by_max_pages(tmp_path):
    spec, page = _paged_spec(tmp_path, "1000", max_pages=3)
    session = FakeSession({"https://example.edu/search": page})
    assert len(_run(_executor(session), spec).bodies) == 3


def test_paginate_non_numeric_total_is_portal_changed(tmp_path):
    spec, page = _paged_spec(tmp_path, "many")
    session = FakeSession({"https://example.edu/search": page})
    with pytest.raises(PortalChanged, match="total"):
        _run(_executor(session), spec)


def test_host_throttle_spaces_requests_per_host():
    clock = iter([0.0, 0.1, 0.1, 5.0]).__next__
    slept: list[float] = []
    throttle = HostThrottle(0.5, clock=clock, sleeper=slept.append)
    throttle.wait("https://a.edu/x")           # t=0.0, first request: no sleep
    throttle.wait("https://a.edu/y")           # t=0.1, must wait until 0.5
    throttle.wait("https://b.edu/z")           # t=0.1, other host: no sleep
    throttle.wait("https://a.edu/w")           # t=5.0, long after: no sleep
    assert slept == [pytest.approx(0.4)]


def test_executor_sets_identifying_user_agent():
    session = FakeSession({})
    ReplayExecutor(session, throttle=HostThrottle(0.0))
    assert "cc-course-finder" in session.headers["User-Agent"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_executor.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.schedule.replay.executor'`.

- [ ] **Step 4: Implement the executor**

Create `src/schedule/replay/executor.py`:

```python
"""Runs a replay spec's HTTP steps and returns the final step's body (or bodies).

One executor per provider instance, so its response cache lives for one college's
lookups within one search. Requests use fixed timeouts, one retry on a connection
error, and a per-host minimum interval shared across threads.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

import requests

from ..errors import PortalChanged
from ..term import ParsedTerm
from .captures import evaluate_capture
from .inputs import render
from .spec import ReplaySpec, Step

REQUEST_TIMEOUT_SECONDS = 20
MIN_INTERVAL_PER_HOST = 0.5
RETRY_DELAY_SECONDS = 1.0
USER_AGENT = "Mozilla/5.0 (compatible; cc-course-finder; +https://github.com/FYC23/CC-course-finder)"


@dataclass(frozen=True)
class ExecutionResult:
    bodies: tuple[str, ...]
    captures: Mapping[str, str]
    final_url: str


class HostThrottle:
    """Keeps at least ``min_interval`` seconds between requests to one host, across threads."""

    def __init__(
        self,
        min_interval: float = MIN_INTERVAL_PER_HOST,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._sleeper = sleeper
        self._next_slot: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        with self._lock:
            now = self._clock()
            send_at = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = send_at + self._min_interval
        delay = send_at - now
        if delay > 0:
            self._sleeper(delay)


_SHARED_THROTTLE = HostThrottle()


class ReplayExecutor:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        throttle: HostThrottle | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)
        self._throttle = throttle or _SHARED_THROTTLE
        self._sleeper = sleeper
        self._cache: dict[tuple, Any] = {}

    def execute(self, spec: ReplaySpec, *, term: ParsedTerm, values: Mapping[str, str]) -> ExecutionResult:
        captures: Mapping[str, str] = MappingProxyType({})
        bodies: tuple[str, ...] = ()
        final_url = ""
        for index, step in enumerate(spec.steps):
            scope = MappingProxyType({**values, **captures})
            response = self._request(step, scope)
            captures = MappingProxyType({**captures, **self._captures_of(step, response, term, scope)})
            if index == len(spec.steps) - 1:
                bodies = (response.text, *self._more_pages(step, scope, captures))
                final_url = str(response.url)
        return ExecutionResult(bodies=bodies, captures=captures, final_url=final_url)

    def _captures_of(self, step: Step, response: Any, term: ParsedTerm, scope: Mapping[str, str]) -> dict[str, str]:
        return {
            name: evaluate_capture(
                name=name, capture=capture, step_id=step.id, response_text=response.text,
                cookies=self._session.cookies, term=term, values=scope,
            )
            for name, capture in step.captures.items()
        }

    def _more_pages(self, step: Step, scope: Mapping[str, str], captures: Mapping[str, str]) -> tuple[str, ...]:
        paginate = step.paginate
        if paginate is None:
            return ()
        total_text = captures.get(paginate.total_capture, "")
        if not total_text.strip().isdigit():
            raise PortalChanged(
                f"step {step.id!r}: pagination total {total_text!r} is not a number"
            )
        pages = min(math.ceil(int(total_text) / paginate.page_size), paginate.max_pages)
        bodies: list[str] = []
        for page in range(1, pages):
            value = str(paginate.first + page * paginate.increment)
            bodies.append(self._request(step, scope, override={paginate.param: value}).text)
        return tuple(bodies)

    def _request(self, step: Step, scope: Mapping[str, str], *, override: Mapping[str, str] | None = None) -> Any:
        url = render(step.url, scope)
        query = {**{k: render(v, scope) for k, v in step.query.items()}, **(override or {})}
        form = {k: render(v, scope) for k, v in step.form.items()}
        json_body = _render_deep(step.json_body, scope) if step.json_body is not None else None
        headers = {k: render(v, scope) for k, v in step.headers.items()}
        key = (step.method, url, tuple(sorted(query.items())), tuple(sorted(form.items())),
               json.dumps(json_body, sort_keys=True))
        if step.cache and key in self._cache:
            return self._cache[key]
        response = self._send(step.method, url, query=query, form=form, json_body=json_body, headers=headers)
        if step.cache:
            self._cache[key] = response
        return response

    def _send(self, method: str, url: str, *, query: dict, form: dict, json_body: Any, headers: dict) -> Any:
        try:
            return self._send_once(method, url, query=query, form=form, json_body=json_body, headers=headers)
        except requests.ConnectionError:
            self._sleeper(RETRY_DELAY_SECONDS)
            return self._send_once(method, url, query=query, form=form, json_body=json_body, headers=headers)

    def _send_once(self, method: str, url: str, *, query: dict, form: dict, json_body: Any, headers: dict) -> Any:
        self._throttle.wait(url)
        response = self._session.request(
            method, url,
            params=query or None,
            data=form or None,
            json=json_body,
            headers=headers or None,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response


def _render_deep(value: Any, scope: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return render(value, scope)
    if isinstance(value, Mapping):
        return {k: _render_deep(v, scope) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_render_deep(v, scope) for v in value]
    return value
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_executor.py -q`
Expected: all PASS.

- [ ] **Step 6: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add src/schedule/replay/executor.py tests/schedule/replay/fakes.py tests/schedule/replay/test_executor.py
git commit -m "feat(schedule): add replay executor with cache, bounded pagination, throttle, and retry"
```

---

### Task 6: Extractor (rows, filters, fields, meetings, modality, status)

**Files:**
- Create: `src/schedule/replay/extractor.py`
- Test: `tests/schedule/replay/test_extractor.py`

**Interfaces:**
- Consumes: `spec.Extract`, `spec.FilterRule`, `spec.MeetingRule`, `spec.ValueRule`, `spec.value_rule` (Task 2); `inputs.render` (Task 3); `jsonpath.resolve` (Task 1); `normalize.compact_code`, `days_from_text`, `location_is_online`, `status_from_seats`, `parse_hhmm`, `parse_date`, `int_or_none`, `normalize_modality`, `normalize_status` (Task 1 and Phase 1); `errors.PortalChanged`.
- Produces: `extractor.extract_sections(bodies: Sequence[str], extract: Extract, values: Mapping[str, str]) -> tuple[ParsedSection, ...]`, `extractor.JsonRow(node)`, `extractor.HtmlRow(element)`, `extractor.text_of(row, rule) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/schedule/replay/test_extractor.py`:

```python
from __future__ import annotations

import json
from datetime import date, time

import pytest

from src.schedule.errors import PortalChanged
from src.schedule.replay.extractor import extract_sections
from src.schedule.replay.spec import (
    Extract, FilterRule, MeetingRule, ValueRule, value_rule,
)

_VALUES = {"subject": "MATH", "number": "400"}


def _json_extract(**overrides) -> Extract:
    base = dict(
        kind="json", rows="$.rows[*]",
        fields={"section_id": ValueRule(path="$.crn"), "title": ValueRule(path="$.title"),
                "instructor": ValueRule(path="$.who"), "seats_total": ValueRule(path="$.max"),
                "seats_used": ValueRule(path="$.used"),
                "course_code_as_listed": ValueRule(join=(ValueRule(path="$.subj"), ValueRule(path="$.num")))},
        status_from_seats=True,
        modality_tokens=(ValueRule(path="$.method"),),
        meetings=(MeetingRule(
            day_flags=tuple(ValueRule(path=f"$.{d}") for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")),
            start=ValueRule(path="$.begin"), end=ValueRule(path="$.end"),
            location=ValueRule(join=(ValueRule(path="$.bldg"), ValueRule(path="$.room"))),
            start_date=ValueRule(path="$.from"), end_date=ValueRule(path="$.to"),
        ),),
    )
    return Extract(**{**base, **overrides})


_ROW_IN_PERSON = {
    "crn": "49060", "title": "Calculus II", "who": "E Enright", "max": 42.0, "used": 36.0,
    "subj": "MATH", "num": "C2220", "method": "LEC",
    "mon": True, "tue": False, "wed": True, "thu": False, "fri": False, "sat": False, "sun": False,
    "begin": "08:00AM", "end": "09:00AM", "bldg": "MTSC", "room": "106",
    "from": "08/24/26", "to": "12/18/26",
}
_ROW_ONLINE = {
    "crn": "49087", "title": "Business Calc", "who": None, "max": 45.0, "used": 45.0,
    "subj": "MATH", "num": "5", "method": "OL",
    "mon": False, "tue": False, "wed": False, "thu": False, "fri": False, "sat": False, "sun": False,
    "begin": None, "end": None, "bldg": "ON", "room": "LINE", "from": "08/24/26", "to": "12/18/26",
}


def test_json_rows_fields_meetings_status_modality():
    body = json.dumps({"rows": [_ROW_IN_PERSON, _ROW_ONLINE]})
    sections = extract_sections([body], _json_extract(), _VALUES)
    assert [s.section_id for s in sections] == ["49060", "49087"]
    first, second = sections
    assert first.title == "Calculus II" and first.instructor == "E Enright"
    assert first.seats_total == 42 and first.seats_used == 36 and first.status == "open"
    assert first.course_code_as_listed == "MATH C2220"
    assert first.modality == "in_person"
    assert first.meetings[0].days == ("M", "W")
    assert first.meetings[0].start_local == time(8, 0) and first.meetings[0].end_local == time(9, 0)
    assert first.meetings[0].location == "MTSC 106" and first.meetings[0].is_online is False
    assert first.meetings[0].start_date == date(2026, 8, 24) and first.meetings[0].end_date == date(2026, 12, 18)
    assert second.instructor == "" and second.status == "closed"
    assert second.modality == "async_online"
    assert second.meetings[0].is_online is True and second.meetings[0].days == ()


def test_empty_meeting_slots_are_skipped():
    row = {**_ROW_IN_PERSON, "mon": False, "wed": False, "begin": None, "end": None, "bldg": None, "room": None}
    sections = extract_sections([json.dumps({"rows": [row]})], _json_extract(), _VALUES)
    assert sections[0].meetings == ()
    assert sections[0].modality == "in_person"  # from the LEC token


def test_each_iterates_nested_meetings():
    extract = _json_extract(meetings=(MeetingRule(
        each="$.meet[*]",
        day_flags=tuple(ValueRule(path=f"$.{d}") for d in ("monDay", "tueDay", "wedDay", "thuDay", "friDay", "satDay", "sunDay")),
        start=ValueRule(path="$.beginTime"), end=ValueRule(path="$.endTime"),
        location=ValueRule(join=(ValueRule(path="$.bldgCode"), ValueRule(path="$.roomCode"))),
    ),), modality_tokens=(ValueRule(path="$.meet[*].schdDesc"),))
    row = {**_ROW_IN_PERSON, "meet": [
        {"beginTime": "1615", "endTime": "1705", "tueDay": "T", "bldgCode": "SEM", "roomCode": "203", "schdDesc": "Lecture"},
        {"bldgCode": "ONLINE", "schdDesc": "Hybrid"},
    ]}
    section = extract_sections([json.dumps({"rows": [row]})], extract, _VALUES)[0]
    assert len(section.meetings) == 2
    assert section.meetings[0].days == ("T",) and section.meetings[0].start_local == time(16, 15)
    assert section.meetings[1].is_online is True and section.meetings[1].start_local is None
    assert section.modality == "hybrid"


def test_filters_compare_normalized_and_render_placeholders():
    extract = _json_extract(filters=(
        FilterRule(value=ValueRule(path="$.camp"), equals="1"),
        FilterRule(value=ValueRule(path="$.num"), any_of=("{number}", "{number}C")),
    ))
    rows = [
        {**_ROW_IN_PERSON, "crn": "a", "camp": "1", "num": "400"},
        {**_ROW_IN_PERSON, "crn": "b", "camp": "1", "num": "400 C"},
        {**_ROW_IN_PERSON, "crn": "c", "camp": "2", "num": "400"},
        {**_ROW_IN_PERSON, "crn": "d", "camp": "1", "num": "401"},
    ]
    sections = extract_sections([json.dumps({"rows": rows})], extract, _VALUES)
    assert [s.section_id for s in sections] == ["a", "b"]


def test_status_rule_beats_seats():
    extract = _json_extract(status=ValueRule(path="$.st"), status_from_seats=False)
    row = {**_ROW_IN_PERSON, "st": "Waitlisted"}
    assert extract_sections([json.dumps({"rows": [row]})], extract, _VALUES)[0].status == "waitlist"


def test_no_status_source_is_unknown():
    extract = _json_extract(status=None, status_from_seats=False)
    assert extract_sections([json.dumps({"rows": [_ROW_IN_PERSON]})], extract, _VALUES)[0].status == "unknown"


def test_modality_map_wins_over_normalization():
    extract = _json_extract(modality_map={"partially online": "hybrid"})
    row = {**_ROW_IN_PERSON, "method": "Partially Online"}
    assert extract_sections([json.dumps({"rows": [row]})], extract, _VALUES)[0].modality == "hybrid"


def test_seats_available_and_wait_capacity_feed_status():
    extract = _json_extract(fields={
        "section_id": ValueRule(path="$.crn"), "seats_available": ValueRule(path="$.avail"),
        "wait_capacity": ValueRule(path="$.wait")})
    body = json.dumps({"rows": [{"crn": "1", "avail": 0, "wait": 20}, {"crn": "2", "avail": 0, "wait": 0}]})
    assert [s.status for s in extract_sections([body], extract, _VALUES)] == ["waitlist", "closed"]


def test_multiple_bodies_are_concatenated():
    bodies = [json.dumps({"rows": [_ROW_IN_PERSON]}), json.dumps({"rows": [_ROW_ONLINE]})]
    assert len(extract_sections(bodies, _json_extract(), _VALUES)) == 2


def test_rows_container_missing_is_portal_changed():
    with pytest.raises(PortalChanged, match="rows"):
        extract_sections([json.dumps({"other": []})], _json_extract(), _VALUES)


def test_rows_container_null_is_no_sections():
    assert extract_sections([json.dumps({"rows": None})], _json_extract(), _VALUES) == ()


def test_rows_container_not_a_list_is_portal_changed():
    with pytest.raises(PortalChanged, match="list"):
        extract_sections([json.dumps({"rows": {"a": 1}})], _json_extract(), _VALUES)


def test_body_not_json_is_portal_changed():
    with pytest.raises(PortalChanged, match="JSON"):
        extract_sections(["<html>"], _json_extract(), _VALUES)


# --- html ------------------------------------------------------------------------------

_HTML = """
<div class='filter-results'><span id='totalResults'>2</span></div>
<ul class='class-cards'>
<li><article class="class-card">
  <div class="title"><span class="class-card-subj-num">
      MATH 400</span> Calculus I</div>
  <span class="college">American River College</span>
  <ul>
    <li class="section"><span class="label">Class</span> LEC&nbsp;10414</li>
    <li><span class="label">Mode</span> In Person</li>
    <li><span class='label'>Day/Time</span>Mon/Wed, 3:00 pm to 5:20 pm</li>
    <li><span class='label'>Building<!-- 1 --></span>Main Campus,
STEM
, 310</li>
    <li><span class='label'>Instructor</span><a href="/x">Karsten Stemmann</a></li>
    <li class="status"><span class='highlight highlight--closed'></span>Closed</li>
  </ul>
</article></li>
<li><article class="class-card">
  <div class="title"><span class="class-card-subj-num">MATH 300</span> Intro Ideas</div>
  <span class="college">American River College</span>
  <ul>
    <li class="section"><span class="label">Class</span> LEC&nbsp;12286</li>
    <li><span class="label">Mode</span> Fully Online</li>
    <li><span class='label'>Day/Time</span>Asynchronous – no scheduled meeting times</li>
    <li><span class='label'>Instructor</span><a href="/y">Trisha R. Butler</a></li>
    <li class="status"><span class='highlight'></span>Open</li>
  </ul>
</article></li>
</ul>
"""


def _html_extract(**overrides) -> Extract:
    kind = "html"
    base = dict(
        kind=kind, rows="article.class-card", marker="div.filter-results",
        fields={
            "section_id": value_rule({"css": "li.section", "regex": r"(\d+)\s*$"}, kind),
            "title": value_rule({"css": "div.title", "regex": r"^[A-Z]+ [A-Z0-9]+\s+(.+)$"}, kind),
            "instructor": value_rule({"css": "li:has(> span.label:-soup-contains('Instructor'))",
                                      "regex": r"^Instructor\s*(.*)$"}, kind),
            "course_code_as_listed": value_rule("span.class-card-subj-num", kind),
        },
        status=value_rule("li.status", kind),
        modality_tokens=(value_rule({"css": "li:has(> span.label:-soup-contains('Mode'))",
                                     "regex": r"^Mode\s*(.*)$"}, kind),),
        modality_map={"partially online": "hybrid"},
        meetings=(MeetingRule(
            time_text=value_rule("li:has(> span.label:-soup-contains('Day/Time'))", kind),
            time_pattern=r"^Day/Time\s*(?P<days>[A-Za-z/]+), (?P<start>\d{1,2}:\d{2} [ap]m) to (?P<end>\d{1,2}:\d{2} [ap]m)",
            location=value_rule({"css": "li:has(> span.label:-soup-contains('Building'))",
                                 "regex": r"^Building\s*(.*)$"}, kind),
        ),),
    )
    return Extract(**{**base, **overrides})


def test_html_rows_fields_and_meeting_text():
    sections = extract_sections([_HTML], _html_extract(), _VALUES)
    assert [s.section_id for s in sections] == ["10414", "12286"]
    first, second = sections
    assert first.title == "Calculus I" and first.instructor == "Karsten Stemmann"
    assert first.course_code_as_listed == "MATH 400" and first.status == "closed"
    assert first.modality == "in_person"
    meeting = first.meetings[0]
    assert meeting.days == ("M", "W")
    assert meeting.start_local == time(15, 0) and meeting.end_local == time(17, 20)
    assert meeting.location == "Main Campus, STEM , 310"
    assert second.status == "open" and second.modality == "async_online"
    assert second.meetings == ()


def test_html_filter_on_course_code():
    extract = _html_extract(filters=(FilterRule(
        value=value_rule("span.class-card-subj-num", "html"), equals="{subject} {number}"),))
    sections = extract_sections([_HTML], extract, _VALUES)
    assert [s.section_id for s in sections] == ["10414"]


def test_html_missing_marker_is_portal_changed():
    with pytest.raises(PortalChanged, match="marker"):
        extract_sections(["<html><body>Maintenance</body></html>"], _html_extract(), _VALUES)


def test_html_no_rows_with_marker_is_no_sections():
    page = "<div class='filter-results'><span id='totalResults'>0</span></div>"
    assert extract_sections([page], _html_extract(), _VALUES) == ()


def test_html_attr_rule():
    extract = _html_extract(fields={"section_id": value_rule({"css": "li a", "attr": "href"}, "html")})
    assert [s.section_id for s in extract_sections([_HTML], extract, _VALUES)] == ["/x", "/y"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_extractor.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.schedule.replay.extractor'`.

- [ ] **Step 3: Implement the extractor**

Create `src/schedule/replay/extractor.py`:

```python
"""Turns a final step's response bodies plus a spec's ``extract`` block into sections.

JSON and HTML rows share one interface (``Row``): ``values(rule)`` returns every string a
value rule selects and ``children(selector)`` returns nested rows (for ``each``). All
field normalization is delegated to ``normalize.py`` so no rule lives in two places.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import time
from typing import Any, Protocol

from bs4 import BeautifulSoup
from bs4.element import Tag

from ..errors import PortalChanged
from ..models import DAY_CODES, Meeting, ParsedSection
from ..normalize import (
    compact_code,
    days_from_text,
    int_or_none,
    location_is_online,
    normalize_modality,
    normalize_status,
    parse_date,
    parse_hhmm,
    status_from_seats,
)
from .inputs import render
from .jsonpath import resolve
from .spec import Extract, FilterRule, MeetingRule, ValueRule

_FALSY = frozenset({"", "false", "0", "no", "n", "none", "null"})


class Row(Protocol):
    def values(self, rule: ValueRule) -> list[str]: ...

    def children(self, selector: str) -> list["Row"]: ...


def text_of(row: Row, rule: ValueRule) -> str:
    values = row.values(rule)
    return values[0] if values else ""


class JsonRow:
    def __init__(self, node: Any) -> None:
        self._node = node

    def values(self, rule: ValueRule) -> list[str]:
        if rule.const is not None:
            return [rule.const]
        if rule.join:
            return [_join(self, rule)]
        texts = [_stringify(m) for m in resolve(self._node, rule.path or "$")]
        return _apply_regex(texts, rule.regex)

    def children(self, selector: str) -> list[Row]:
        return [JsonRow(n) for n in resolve(self._node, selector)]


class HtmlRow:
    def __init__(self, element: Tag) -> None:
        self._element = element

    def values(self, rule: ValueRule) -> list[str]:
        if rule.const is not None:
            return [rule.const]
        if rule.join:
            return [_join(self, rule)]
        elements = self._element.select(rule.css) if rule.css else [self._element]
        return _apply_regex([_element_text(el, rule.attr) for el in elements], rule.regex)

    def children(self, selector: str) -> list[Row]:
        return [HtmlRow(el) for el in self._element.select(selector)]


def _join(row: Row, rule: ValueRule) -> str:
    return rule.sep.join(part for part in (text_of(row, r) for r in rule.join) if part)


def _apply_regex(texts: list[str], pattern: str | None) -> list[str]:
    if pattern is None:
        return texts
    out: list[str] = []
    for text in texts:
        match = re.search(pattern, text)
        if match is not None:
            out.append(match.group(1) if match.groups() else match.group(0))
    return out


def _stringify(value: Any) -> str:
    if value is None or value is False:
        return ""
    if value is True:
        return "true"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _element_text(element: Tag, attr: str | None) -> str:
    if attr:
        value = element.get(attr)
        return str(value).strip() if value is not None else ""
    return " ".join(element.get_text(" ").split())


# --- rows ------------------------------------------------------------------------------


def extract_sections(
    bodies: Sequence[str], extract: Extract, values: Mapping[str, str]
) -> tuple[ParsedSection, ...]:
    sections: list[ParsedSection] = []
    for body in bodies:
        for row in _rows(body, extract):
            if _passes_filters(row, extract.filters, values):
                sections.append(_section(row, extract))
    return tuple(sections)


def _rows(body: str, extract: Extract) -> list[Row]:
    if extract.kind == "json":
        return _json_rows(body, extract.rows)
    return _html_rows(body, extract)


def _json_rows(body: str, rows_path: str) -> list[Row]:
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PortalChanged(f"response is not JSON: {exc}") from exc
    containers = resolve(doc, rows_path.removesuffix("[*]"))
    if not containers:
        raise PortalChanged(f"rows path {rows_path!r} not found in response")
    container = containers[0]
    if container is None:
        return []
    if not isinstance(container, list):
        raise PortalChanged(f"rows path {rows_path!r} does not select a list")
    return [JsonRow(node) for node in container]


def _html_rows(body: str, extract: Extract) -> list[Row]:
    soup = BeautifulSoup(body, "html.parser")
    if extract.marker and soup.select_one(extract.marker) is None:
        raise PortalChanged(f"page marker {extract.marker!r} not found")
    return [HtmlRow(el) for el in soup.select(extract.rows)]


def _passes_filters(row: Row, filters: Sequence[FilterRule], values: Mapping[str, str]) -> bool:
    for rule in filters:
        actual = compact_code(text_of(row, rule.value))
        wanted = [rule.equals] if rule.equals is not None else list(rule.any_of)
        if actual not in {compact_code(render(w, values)) for w in wanted}:
            return False
    return True


# --- one section ------------------------------------------------------------------------


def _section(row: Row, extract: Extract) -> ParsedSection:
    fields = {name: text_of(row, rule) for name, rule in extract.fields.items()}
    meetings = _meetings(row, extract.meetings)
    seats = {
        key: int_or_none(fields.get(key))
        for key in ("seats_total", "seats_used", "seats_available", "wait_capacity")
    }
    return ParsedSection(
        section_id=fields.get("section_id", ""),
        status=_status(row, extract, seats),
        modality=_modality(row, extract, meetings),
        title=fields.get("title", ""),
        instructor=fields.get("instructor", ""),
        meetings=meetings,
        seats_total=seats["seats_total"],
        seats_used=seats["seats_used"],
        course_code_as_listed=fields.get("course_code_as_listed", ""),
    )


def _status(row: Row, extract: Extract, seats: Mapping[str, int | None]) -> str:
    if extract.status is not None:
        return normalize_status(text_of(row, extract.status))
    if extract.status_from_seats:
        return status_from_seats(**seats)
    return "unknown"


def _modality(row: Row, extract: Extract, meetings: tuple[Meeting, ...]) -> str:
    tokens = [t for rule in extract.modality_tokens for t in row.values(rule) if t]
    for token in tokens:
        mapped = extract.modality_map.get(token.lower())
        if mapped is not None:
            return mapped
    return normalize_modality(raw_tokens=tokens, meetings=meetings)


def _meetings(row: Row, rules: Sequence[MeetingRule]) -> tuple[Meeting, ...]:
    out: list[Meeting] = []
    for rule in rules:
        scopes = row.children(rule.each) if rule.each else [row]
        for scope in scopes:
            meeting = _meeting(scope, rule)
            if meeting is not None:
                out.append(meeting)
    return tuple(out)


def _meeting(scope: Row, rule: MeetingRule) -> Meeting | None:
    days, start, end = _days_and_times(scope, rule)
    location = text_of(scope, rule.location) if rule.location else ""
    if not days and start is None and not location:
        return None
    return Meeting(
        days=days,
        start_local=start,
        end_local=end,
        location=location,
        is_online=location_is_online(location),
        start_date=parse_date(text_of(scope, rule.start_date)) if rule.start_date else None,
        end_date=parse_date(text_of(scope, rule.end_date)) if rule.end_date else None,
    )


def _days_and_times(scope: Row, rule: MeetingRule) -> tuple[tuple[str, ...], time | None, time | None]:
    start = parse_hhmm(text_of(scope, rule.start)) if rule.start else None
    end = parse_hhmm(text_of(scope, rule.end)) if rule.end else None
    days: tuple[str, ...] = ()
    if rule.day_flags:
        flags = [text_of(scope, flag) for flag in rule.day_flags]
        days = tuple(code for code, flag in zip(DAY_CODES, flags) if _truthy(flag))
    elif rule.day_text is not None:
        days = days_from_text(text_of(scope, rule.day_text))
    elif rule.time_text is not None and rule.time_pattern:
        match = re.search(rule.time_pattern, text_of(scope, rule.time_text))
        if match is not None:
            groups = match.groupdict()
            days = days_from_text(groups.get("days"))
            start = parse_hhmm(groups.get("start"))
            end = parse_hhmm(groups.get("end"))
    return days, start, end


def _truthy(text: str) -> bool:
    return text.strip().lower() not in _FALSY
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_extractor.py -q`
Expected: all PASS. Two things to watch: `li:has(> span.label:-soup-contains('Instructor'))` needs soupsieve ≥ 2.1 (installed in Task 4), and the Los Rios building text collapses to `Main Campus, STEM , 310` because the source has a newline before the comma; the test asserts that literal string.

- [ ] **Step 5: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add src/schedule/replay/extractor.py tests/schedule/replay/test_extractor.py
git commit -m "feat(schedule): add replay extractor for JSON and HTML rows with meetings and filters"
```

---

### Task 7: GenericReplayProvider and wiring (catalog, composite, service)

**Files:**
- Create: `src/schedule/generic_replay.py`
- Modify: `src/schedule/catalog.py` (`KNOWN_SYSTEMS`)
- Modify: `src/schedule/composite.py` (register last)
- Modify: `src/schedule/service.py` (`_lookup_error_reason`)
- Test: `tests/schedule/test_generic_replay.py`, `tests/schedule/test_catalog.py`, `tests/schedule/test_service_parallel.py`

**Interfaces:**
- Consumes: `registry.load_all_specs`, `spec.ReplaySpec`, `inputs.build_values`, `executor.ReplayExecutor`, `extractor.extract_sections`, `errors.PortalChanged`.
- Produces: `generic_replay.GenericReplayProvider(session=None, *, executor: ReplayExecutor | None = None, specs: Mapping[int, ReplaySpec] | None = None)` implementing `ScheduleProvider`; `supports_source` is true only for `system == "replay"` with a loaded spec for that `cc_id`.
- Produces: catalog accepts `"system": "replay"`; `service._lookup_error_reason` returns `"The college's schedule site changed; this lookup needs to be re-recorded."` for `PortalChanged`.

- [ ] **Step 1: Write the failing provider tests**

Create `tests/schedule/test_generic_replay.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from src.schedule.errors import PortalChanged
from src.schedule.generic_replay import GenericReplayProvider
from src.schedule.models import CollegeScheduleSource
from src.schedule.replay.executor import HostThrottle, ReplayExecutor
from src.schedule.replay.spec import load_spec
from src.schedule.term import TermNotListedError, parse_term_label
from tests.schedule.replay.fakes import FakeSession

_SPEC = {
    "cc_id": 999, "cc_name": "Test College", "version": 1, "recorded_at": "2026-09-23",
    "probe": {"course_code": "MATH 1", "term": "Fall 2026"},
    "inputs": {"term": {"format": "{yyyy}{SEASON}", "seasons": {"fall": "70"}}},
    "steps": [{"id": "search", "method": "GET", "url": "https://example.edu/api",
               "query": {"term": "{term}", "subj": "{subject}", "num": "{number}"}}],
    "extract": {"kind": "json", "rows": "$.data[*]",
                "fields": {"section_id": "$.crn", "title": "$.title", "seats_available": "$.avail"},
                "status": {"from_seats": True}},
}
_SOURCE = CollegeScheduleSource(cc_id=999, cc_name="Test College", system="replay",
                                base_url="https://example.edu", locations=())
_OTHER = CollegeScheduleSource(cc_id=62, cc_name="Mt SAC", system="banner9_ssb",
                               base_url="https://prodrg.mtsac.edu", locations=())
_FALL = parse_term_label("Fall 2026")


@pytest.fixture
def spec(tmp_path: Path):
    path = tmp_path / "999.json"
    path.write_text(json.dumps(_SPEC))
    return load_spec(path)


def _provider(spec, session: FakeSession) -> GenericReplayProvider:
    executor = ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None)
    return GenericReplayProvider(executor=executor, specs=MappingProxyType({999: spec}))


def test_supports_only_replay_sources_with_a_spec(spec):
    provider = _provider(spec, FakeSession({}))
    assert provider.supports_source(_SOURCE)
    assert not provider.supports_source(_OTHER)
    unknown = CollegeScheduleSource(cc_id=1, cc_name="X", system="replay", base_url="https://x", locations=())
    assert not provider.supports_source(unknown)


def test_search_course_returns_sections(spec):
    body = json.dumps({"data": [{"crn": "1", "title": "Calc", "avail": 3}, {"crn": "2", "title": "Calc", "avail": 0}]})
    session = FakeSession({"https://example.edu/api": body})
    out = _provider(spec, session).search_course(source=_SOURCE, term=_FALL, course_code="MATH 1")
    assert out.offered is True
    assert [s.section_id for s in out.sections] == ["1", "2"]
    assert [s.status for s in out.sections] == ["open", "closed"]
    assert out.cc_id == 999 and out.cc_name == "Test College"
    assert out.term == "Fall 2026" and out.course_code == "MATH 1"
    assert out.source_url == "https://example.edu/api"
    assert "2 section(s)" in out.raw_summary and out.lookup_error is None
    assert session.calls[0]["params"] == {"term": "202670", "subj": "MATH", "num": "1"}


def test_search_course_no_rows_is_not_offered(spec):
    session = FakeSession({"https://example.edu/api": json.dumps({"data": []})})
    out = _provider(spec, session).search_course(source=_SOURCE, term=_FALL, course_code="MATH 1")
    assert out.offered is False and out.sections == []


def test_search_course_wrong_system_raises(spec):
    with pytest.raises(ValueError, match="does not support"):
        _provider(spec, FakeSession({})).search_course(source=_OTHER, term=_FALL, course_code="MATH 1")


def test_portal_changed_propagates(spec):
    session = FakeSession({"https://example.edu/api": json.dumps({"nope": []})})
    with pytest.raises(PortalChanged):
        _provider(spec, session).search_course(source=_SOURCE, term=_FALL, course_code="MATH 1")


def test_unknown_season_is_term_not_listed(spec):
    with pytest.raises(TermNotListedError):
        _provider(spec, FakeSession({})).search_course(
            source=_SOURCE, term=parse_term_label("Spring 2027"), course_code="MATH 1")


def test_default_constructor_loads_committed_specs():
    provider = GenericReplayProvider()
    assert not provider.supports_source(_OTHER)
```

- [ ] **Step 2: Write the failing catalog and service tests**

Append to `tests/schedule/test_catalog.py`:

```python
def test_replay_system_is_known():
    _validate_entry({**_VALID_ENTRY, "system": "replay", "locations": []})  # must not raise
```

Append to `tests/schedule/test_service_parallel.py`:

```python
from src.schedule.errors import PortalChanged  # noqa: E402
from src.schedule.service import _lookup_error_reason  # noqa: E402
from src.schedule.term import parse_term_label as _parse_term  # noqa: E402


def test_portal_changed_has_a_student_facing_reason() -> None:
    reason = _lookup_error_reason(PortalChanged("rows path not found"), _parse_term("Fall 2026"))
    assert reason == "The college's schedule site changed; this lookup needs to be re-recorded."
    assert "rows path" not in reason
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/test_generic_replay.py tests/schedule/test_catalog.py tests/schedule/test_service_parallel.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.schedule.generic_replay'`, `ValueError: Unknown system 'replay'`, and the reason assertion failing with the generic message.

- [ ] **Step 4: Implement the provider**

Create `src/schedule/generic_replay.py`:

```python
"""ScheduleProvider that replays a recorded per-college spec (system == "replay").

Specs are data files under src/schedule/data/specs/. The provider builds placeholder
values from the term and course code, runs the spec's HTTP steps through a
ReplayExecutor (one per provider instance, so one HTTP session and response cache per
college per search), and extracts sections with the spec's extract block.
"""
from __future__ import annotations

from collections.abc import Mapping

import requests

from .models import CollegeScheduleSource, CourseAvailability
from .replay.executor import ReplayExecutor
from .replay.extractor import extract_sections
from .replay.inputs import build_values
from .replay.registry import load_all_specs
from .replay.spec import ReplaySpec
from .term import ParsedTerm

REPLAY_SYSTEM = "replay"


class GenericReplayProvider:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        executor: ReplayExecutor | None = None,
        specs: Mapping[int, ReplaySpec] | None = None,
    ) -> None:
        self._executor = executor or ReplayExecutor(session)
        self._specs = specs if specs is not None else load_all_specs()

    def supports_source(self, source: CollegeScheduleSource) -> bool:
        return source.system == REPLAY_SYSTEM and source.cc_id in self._specs

    def search_course(
        self, *, source: CollegeScheduleSource, term: ParsedTerm, course_code: str
    ) -> CourseAvailability:
        if not self.supports_source(source):
            raise ValueError(
                f"GenericReplayProvider does not support system={source.system!r} cc_id={source.cc_id}"
            )
        spec = self._specs[source.cc_id]
        values = build_values(spec.inputs, term, course_code)
        result = self._executor.execute(spec, term=term, values=values)
        sections = extract_sections(result.bodies, spec.extract, values)
        return CourseAvailability(
            cc_id=source.cc_id,
            cc_name=source.cc_name,
            term=term.label,
            course_code=course_code,
            offered=bool(sections),
            sections=list(sections),
            source_url=result.final_url or source.base_url,
            raw_summary=(
                f"{len(sections)} section(s) via replay spec cc_id={spec.cc_id} "
                f"v{spec.version} ({len(result.bodies)} page(s))"
            ),
        )
```

- [ ] **Step 5: Wire catalog, composite, and service**

In `src/schedule/catalog.py`, add `"replay"` to `KNOWN_SYSTEMS`:

```python
KNOWN_SYSTEMS: frozenset[str] = frozenset(
    {
        "colleague_selfservice",
        "banner9_ssb",
        "wvm_static",
        "vsb_4cd",
        "marin_colleague",
        "smcccd_colleague",
        "replay",
    }
)
```

In `src/schedule/composite.py`, import and register the provider last (hand-written adapters win when both could match):

```python
from .generic_replay import GenericReplayProvider
```

```python
def build_composite_provider() -> CompositeProvider:
    return CompositeProvider([
        ColleagueSelfServiceProvider(),
        Banner9SsbProvider(),
        WvmStaticProvider(),
        Vsb4cdProvider(),
        MarinColleagueProvider(),
        SmcccdColleagueProvider(),
        GenericReplayProvider(),
    ])
```

In `src/schedule/service.py`, import `PortalChanged` and add a branch to `_lookup_error_reason` before the final generic return:

```python
from .errors import PortalChanged
```

```python
    if isinstance(err, TermNotListedError):
        return f"{term.label} isn't listed on the college's schedule site."
    if isinstance(err, PortalChanged):
        return "The college's schedule site changed; this lookup needs to be re-recorded."
    return "Something went wrong reading the college's schedule."
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/test_generic_replay.py tests/schedule/test_catalog.py tests/schedule/test_service_parallel.py -q`
Expected: all PASS.

- [ ] **Step 7: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add src/schedule/generic_replay.py src/schedule/catalog.py src/schedule/composite.py src/schedule/service.py tests/schedule/test_generic_replay.py tests/schedule/test_catalog.py tests/schedule/test_service_parallel.py
git commit -m "feat(schedule): add GenericReplayProvider and register the replay system"
```

---

### Task 8: Riverside district specs (Riverside City, Norco, Moreno Valley)

Portal facts (verified live 2026-09-23): anonymous SharePoint OData at `https://apps-studentrcc.msappproxy.net/schedule/_api/web/lists/getByTitle('ScheduleData_{RIV|NOR|MOV}')/items`. `$filter=Term eq '26FAL' and Primary_x0020_Subject eq 'MATH-C2220'` returns 4 rows; `Term` codes `26FAL`, `26SUM`, `26SPR` all return rows (Fall/Summer/Spring). Whole-subject queries return under 100 rows, so `$top=500` needs no paging. Rows carry up to six meeting slots (`Day{n}Mon..Sun`, `Start_x0020_Time_x0020_{n}`, `Building_x0020_{n}`, `Room_x0020_{n}`), method tokens `LEC`, `LAB`, `OL`, `HYB`, and online rows use `Building_x0020_1 = "ON"`, `Room_x0020_1 = "LINE"`, null times.

Known limitation (Phase 3 fixes it): ASSIST lists Riverside's calculus as `MAT 1B`; the live code is `MATH-C2220`. The spec sends `MAT-1B` and gets zero rows, so the UI shows "Not offered" for those courses until the alias table lands. The row's `Prerequisite` text ("MATH-C2220 was formerly MAT-1B") is an alias source for Phase 3. Record this in each catalog entry's `note`.

**Files:**
- Create: `src/schedule/data/specs/78.json`, `src/schedule/data/specs/148.json`, `src/schedule/data/specs/149.json`
- Create: `tests/fixtures/replay/rccd_riv_sample.json`
- Modify: `src/schedule/data/colleges.json`
- Test: `tests/schedule/replay/test_specs_registry.py`, `tests/schedule/replay/test_specs_rccd.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: three loadable specs and three catalog entries with `system: "replay"`; a registry integrity test every later spec task relies on.

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/replay/rccd_riv_sample.json` (two real rows fetched 2026-09-23, trimmed to the spec's `$select` fields; row one is MATH-C2220 section 49060, row two is an online MATH-5 section 49087):

```json
{
  "value": [
    {
      "Title": "Calculus II: Early Transcendentals",
      "College": "Riverside",
      "Term": "26FAL",
      "Primary_x0020_Subject": "MATH-C2220",
      "Section_x0020_Number": "49060",
      "Instructor_x0020_Method_x0020_1": "LEC",
      "Instructor_x0020_Method_x0020_2": "LEC2",
      "Faculty_x0020_Name_x0020_1": "E Enright",
      "Total_x0020_Seats": 42.0,
      "Seats_x0020_Used": 36.0,
      "Start_x0020_Date_x0020_1": "08/24/26", "End_x0020_Date_x0020_1": "12/18/26",
      "Start_x0020_Time_x0020_1": "08:00AM", "End_x0020_Time_x0020_1": "09:00AM",
      "Day1Mon": true, "Day1Tue": false, "Day1Wed": false, "Day1Thu": false, "Day1Fri": false, "Day1Sat": false, "Day1Sun": false,
      "Building_x0020_1": "MTSC", "Room_x0020_1": "106",
      "Start_x0020_Date_x0020_2": "08/24/26", "End_x0020_Date_x0020_2": "12/18/26",
      "Start_x0020_Time_x0020_2": "08:00AM", "End_x0020_Time_x0020_2": "08:55AM",
      "Day2Mon": false, "Day2Tue": false, "Day2Wed": true, "Day2Thu": false, "Day2Fri": true, "Day2Sat": false, "Day2Sun": false,
      "Building_x0020_2": "MTSC", "Room_x0020_2": "106",
      "Start_x0020_Date_x0020_3": "08/24/26", "End_x0020_Date_x0020_3": "12/18/26",
      "Start_x0020_Time_x0020_3": "09:10AM", "End_x0020_Time_x0020_3": "10:05AM",
      "Day3Mon": true, "Day3Tue": false, "Day3Wed": false, "Day3Thu": false, "Day3Fri": false, "Day3Sat": false, "Day3Sun": false,
      "Building_x0020_3": "MTSC", "Room_x0020_3": "106",
      "Start_x0020_Date_x0020_4": "08/24/26", "End_x0020_Date_x0020_4": "12/18/26",
      "Start_x0020_Time_x0020_4": "09:05AM", "End_x0020_Time_x0020_4": "10:05AM",
      "Day4Mon": false, "Day4Tue": false, "Day4Wed": true, "Day4Thu": false, "Day4Fri": false, "Day4Sat": false, "Day4Sun": false,
      "Building_x0020_4": "MTSC", "Room_x0020_4": "106",
      "Start_x0020_Date_x0020_5": "08/24/26", "End_x0020_Date_x0020_5": "12/18/26",
      "Start_x0020_Time_x0020_5": "09:05AM", "End_x0020_Time_x0020_5": "10:00AM",
      "Day5Mon": false, "Day5Tue": false, "Day5Wed": false, "Day5Thu": false, "Day5Fri": true, "Day5Sat": false, "Day5Sun": false,
      "Building_x0020_5": "MTSC", "Room_x0020_5": "106",
      "Start_x0020_Date_x0020_6": null, "End_x0020_Date_x0020_6": null,
      "Start_x0020_Time_x0020_6": null, "End_x0020_Time_x0020_6": null,
      "Day6Mon": false, "Day6Tue": false, "Day6Wed": false, "Day6Thu": false, "Day6Fri": false, "Day6Sat": false, "Day6Sun": false,
      "Building_x0020_6": null, "Room_x0020_6": null
    },
    {
      "Title": "Calculus for Business and Life Science",
      "College": "Riverside",
      "Term": "26FAL",
      "Primary_x0020_Subject": "MATH-5",
      "Section_x0020_Number": "49087",
      "Instructor_x0020_Method_x0020_1": "OL",
      "Instructor_x0020_Method_x0020_2": null,
      "Faculty_x0020_Name_x0020_1": "A Curtis",
      "Total_x0020_Seats": 45.0,
      "Seats_x0020_Used": 33.0,
      "Start_x0020_Date_x0020_1": "08/24/26", "End_x0020_Date_x0020_1": "12/18/26",
      "Start_x0020_Time_x0020_1": null, "End_x0020_Time_x0020_1": null,
      "Day1Mon": false, "Day1Tue": false, "Day1Wed": false, "Day1Thu": false, "Day1Fri": false, "Day1Sat": false, "Day1Sun": false,
      "Building_x0020_1": "ON", "Room_x0020_1": "LINE",
      "Start_x0020_Date_x0020_2": null, "End_x0020_Date_x0020_2": null,
      "Start_x0020_Time_x0020_2": null, "End_x0020_Time_x0020_2": null,
      "Day2Mon": false, "Day2Tue": false, "Day2Wed": false, "Day2Thu": false, "Day2Fri": false, "Day2Sat": false, "Day2Sun": false,
      "Building_x0020_2": null, "Room_x0020_2": null,
      "Start_x0020_Date_x0020_3": null, "End_x0020_Date_x0020_3": null,
      "Start_x0020_Time_x0020_3": null, "End_x0020_Time_x0020_3": null,
      "Day3Mon": false, "Day3Tue": false, "Day3Wed": false, "Day3Thu": false, "Day3Fri": false, "Day3Sat": false, "Day3Sun": false,
      "Building_x0020_3": null, "Room_x0020_3": null,
      "Start_x0020_Date_x0020_4": null, "End_x0020_Date_x0020_4": null,
      "Start_x0020_Time_x0020_4": null, "End_x0020_Time_x0020_4": null,
      "Day4Mon": false, "Day4Tue": false, "Day4Wed": false, "Day4Thu": false, "Day4Fri": false, "Day4Sat": false, "Day4Sun": false,
      "Building_x0020_4": null, "Room_x0020_4": null,
      "Start_x0020_Date_x0020_5": null, "End_x0020_Date_x0020_5": null,
      "Start_x0020_Time_x0020_5": null, "End_x0020_Time_x0020_5": null,
      "Day5Mon": false, "Day5Tue": false, "Day5Wed": false, "Day5Thu": false, "Day5Fri": false, "Day5Sat": false, "Day5Sun": false,
      "Building_x0020_5": null, "Room_x0020_5": null,
      "Start_x0020_Date_x0020_6": null, "End_x0020_Date_x0020_6": null,
      "Start_x0020_Time_x0020_6": null, "End_x0020_Time_x0020_6": null,
      "Day6Mon": false, "Day6Tue": false, "Day6Wed": false, "Day6Thu": false, "Day6Fri": false, "Day6Sat": false, "Day6Sun": false,
      "Building_x0020_6": null, "Room_x0020_6": null
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/schedule/replay/test_specs_registry.py`:

```python
"""Data integrity: every catalog entry with system "replay" has a valid spec and vice versa."""
from __future__ import annotations

from src.schedule.catalog import list_college_sources
from src.schedule.replay.registry import SPECS_DIR, load_all_specs, load_specs_from


def test_all_committed_specs_load():
    specs = load_specs_from(SPECS_DIR)
    assert specs == load_all_specs()


def test_every_replay_catalog_entry_has_a_spec_and_every_spec_a_catalog_entry():
    catalog_ids = {s.cc_id for s in list_college_sources() if s.system == "replay"}
    spec_ids = set(load_all_specs())
    assert catalog_ids == spec_ids


def test_spec_names_match_catalog_names():
    by_id = {s.cc_id: s for s in list_college_sources()}
    for cc_id, spec in load_all_specs().items():
        assert spec.cc_name == by_id[cc_id].cc_name
```

Create `tests/schedule/replay/test_specs_rccd.py`:

```python
"""Riverside district specs (78, 148, 149) against a recorded OData sample."""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from src.schedule.catalog import get_college_source
from src.schedule.generic_replay import GenericReplayProvider
from src.schedule.replay.executor import HostThrottle, ReplayExecutor
from src.schedule.term import parse_term_label

from .fakes import FakeSession

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "replay"
_HOST = "https://apps-studentrcc.msappproxy.net/schedule/_api/web/lists/getByTitle('ScheduleData_"


def _provider(session: FakeSession) -> GenericReplayProvider:
    return GenericReplayProvider(
        executor=ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None))


@pytest.mark.parametrize("cc_id,list_code", [(78, "RIV"), (148, "NOR"), (149, "MOV")])
def test_request_shape_and_term_codes(cc_id: int, list_code: str):
    session = FakeSession({_HOST: (_FIXTURES / "rccd_riv_sample.json").read_text()})
    source = get_college_source(cc_id)
    _provider(session).search_course(source=source, term=parse_term_label("Fall 2026"), course_code="MAT 1B")
    call = session.calls[0]
    assert call["url"] == f"{_HOST}{list_code}')/items"
    assert call["params"]["$filter"] == "Term eq '26FAL' and Primary_x0020_Subject eq 'MAT-1B'"
    assert call["params"]["$top"] == "500"
    assert call["headers"]["Accept"] == "application/json;odata=nometadata"


@pytest.mark.parametrize("label,code", [("Spring 2027", "27SPR"), ("Summer 2026", "26SUM")])
def test_other_seasons(label: str, code: str):
    session = FakeSession({_HOST: '{"value": []}'})
    _provider(session).search_course(source=get_college_source(78), term=parse_term_label(label), course_code="MATH C2220")
    assert session.calls[0]["params"]["$filter"] == f"Term eq '{code}' and Primary_x0020_Subject eq 'MATH-C2220'"


def test_sections_meetings_seats_and_modality():
    session = FakeSession({_HOST: (_FIXTURES / "rccd_riv_sample.json").read_text()})
    out = _provider(session).search_course(
        source=get_college_source(78), term=parse_term_label("Fall 2026"), course_code="MATH C2220")
    assert out.offered is True and out.lookup_error is None
    lecture, online = out.sections
    assert lecture.section_id == "49060" and lecture.title == "Calculus II: Early Transcendentals"
    assert lecture.instructor == "E Enright" and lecture.course_code_as_listed == "MATH-C2220"
    assert lecture.seats_total == 42 and lecture.seats_used == 36 and lecture.status == "open"
    assert lecture.modality == "in_person"
    assert len(lecture.meetings) == 5
    assert lecture.meetings[0].days == ("M",) and lecture.meetings[0].start_local == time(8, 0)
    assert lecture.meetings[1].days == ("W", "F") and lecture.meetings[1].end_local == time(8, 55)
    assert lecture.meetings[0].location == "MTSC 106" and lecture.meetings[0].is_online is False
    assert lecture.meetings[0].start_date == date(2026, 8, 24) and lecture.meetings[0].end_date == date(2026, 12, 18)
    assert online.section_id == "49087" and online.modality == "async_online"
    assert len(online.meetings) == 1 and online.meetings[0].is_online is True
    assert online.meetings[0].days == () and online.meetings[0].start_local is None
    assert online.status == "open"


def test_empty_value_is_not_offered():
    session = FakeSession({_HOST: '{"value": []}'})
    out = _provider(session).search_course(
        source=get_college_source(78), term=parse_term_label("Fall 2026"), course_code="MAT 1B")
    assert out.offered is False and out.sections == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_specs_registry.py tests/schedule/replay/test_specs_rccd.py -q`
Expected: FAIL with `KeyError: 'No schedule source configured for cc_id=78'` (catalog entries missing) and an empty registry.

- [ ] **Step 4: Write the Riverside City College spec**

Create `src/schedule/data/specs/78.json`:

```json
{
  "cc_id": 78,
  "cc_name": "Riverside City College",
  "version": 1,
  "recorded_at": "2026-09-23",
  "notes": "RCCD Class Finder: anonymous SharePoint OData list per campus (RIV/NOR/MOV). Term codes verified: 26FAL, 26SUM, 26SPR. Whole-subject result sets are under 100 rows, so $top=500 needs no paging. ASSIST codes like MAT 1B differ from live codes like MATH-C2220 until Phase 3 aliases.",
  "probe": { "course_code": "MATH-C2220", "term": "Fall 2026", "expect_min_rows": 1 },
  "inputs": {
    "term": { "format": "{yy}{SEASON}", "seasons": { "fall": "FAL", "spring": "SPR", "summer": "SUM" } },
    "named": { "course": { "from": "course_code", "transform": "dash_join" } }
  },
  "steps": [
    {
      "id": "search",
      "method": "GET",
      "url": "https://apps-studentrcc.msappproxy.net/schedule/_api/web/lists/getByTitle('ScheduleData_RIV')/items",
      "query": {
        "$filter": "Term eq '{term}' and Primary_x0020_Subject eq '{course}'",
        "$select": "Title,Section_x0020_Number,Primary_x0020_Subject,College,Term,Instructor_x0020_Method_x0020_1,Instructor_x0020_Method_x0020_2,Faculty_x0020_Name_x0020_1,Total_x0020_Seats,Seats_x0020_Used,Start_x0020_Date_x0020_1,End_x0020_Date_x0020_1,Start_x0020_Time_x0020_1,End_x0020_Time_x0020_1,Day1Mon,Day1Tue,Day1Wed,Day1Thu,Day1Fri,Day1Sat,Day1Sun,Building_x0020_1,Room_x0020_1,Start_x0020_Date_x0020_2,End_x0020_Date_x0020_2,Start_x0020_Time_x0020_2,End_x0020_Time_x0020_2,Day2Mon,Day2Tue,Day2Wed,Day2Thu,Day2Fri,Day2Sat,Day2Sun,Building_x0020_2,Room_x0020_2,Start_x0020_Date_x0020_3,End_x0020_Date_x0020_3,Start_x0020_Time_x0020_3,End_x0020_Time_x0020_3,Day3Mon,Day3Tue,Day3Wed,Day3Thu,Day3Fri,Day3Sat,Day3Sun,Building_x0020_3,Room_x0020_3,Start_x0020_Date_x0020_4,End_x0020_Date_x0020_4,Start_x0020_Time_x0020_4,End_x0020_Time_x0020_4,Day4Mon,Day4Tue,Day4Wed,Day4Thu,Day4Fri,Day4Sat,Day4Sun,Building_x0020_4,Room_x0020_4,Start_x0020_Date_x0020_5,End_x0020_Date_x0020_5,Start_x0020_Time_x0020_5,End_x0020_Time_x0020_5,Day5Mon,Day5Tue,Day5Wed,Day5Thu,Day5Fri,Day5Sat,Day5Sun,Building_x0020_5,Room_x0020_5,Start_x0020_Date_x0020_6,End_x0020_Date_x0020_6,Start_x0020_Time_x0020_6,End_x0020_Time_x0020_6,Day6Mon,Day6Tue,Day6Wed,Day6Thu,Day6Fri,Day6Sat,Day6Sun,Building_x0020_6,Room_x0020_6",
        "$top": "500"
      },
      "headers": { "Accept": "application/json;odata=nometadata" }
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
      "course_code_as_listed": "$.Primary_x0020_Subject"
    },
    "status": { "from_seats": true },
    "modality": { "tokens": ["$.Instructor_x0020_Method_x0020_1", "$.Instructor_x0020_Method_x0020_2"] },
    "meetings": [
      { "days": { "flags": ["$.Day1Mon", "$.Day1Tue", "$.Day1Wed", "$.Day1Thu", "$.Day1Fri", "$.Day1Sat", "$.Day1Sun"] },
        "start": "$.Start_x0020_Time_x0020_1", "end": "$.End_x0020_Time_x0020_1",
        "location": { "join": ["$.Building_x0020_1", "$.Room_x0020_1"] },
        "start_date": "$.Start_x0020_Date_x0020_1", "end_date": "$.End_x0020_Date_x0020_1" },
      { "days": { "flags": ["$.Day2Mon", "$.Day2Tue", "$.Day2Wed", "$.Day2Thu", "$.Day2Fri", "$.Day2Sat", "$.Day2Sun"] },
        "start": "$.Start_x0020_Time_x0020_2", "end": "$.End_x0020_Time_x0020_2",
        "location": { "join": ["$.Building_x0020_2", "$.Room_x0020_2"] },
        "start_date": "$.Start_x0020_Date_x0020_2", "end_date": "$.End_x0020_Date_x0020_2" },
      { "days": { "flags": ["$.Day3Mon", "$.Day3Tue", "$.Day3Wed", "$.Day3Thu", "$.Day3Fri", "$.Day3Sat", "$.Day3Sun"] },
        "start": "$.Start_x0020_Time_x0020_3", "end": "$.End_x0020_Time_x0020_3",
        "location": { "join": ["$.Building_x0020_3", "$.Room_x0020_3"] },
        "start_date": "$.Start_x0020_Date_x0020_3", "end_date": "$.End_x0020_Date_x0020_3" },
      { "days": { "flags": ["$.Day4Mon", "$.Day4Tue", "$.Day4Wed", "$.Day4Thu", "$.Day4Fri", "$.Day4Sat", "$.Day4Sun"] },
        "start": "$.Start_x0020_Time_x0020_4", "end": "$.End_x0020_Time_x0020_4",
        "location": { "join": ["$.Building_x0020_4", "$.Room_x0020_4"] },
        "start_date": "$.Start_x0020_Date_x0020_4", "end_date": "$.End_x0020_Date_x0020_4" },
      { "days": { "flags": ["$.Day5Mon", "$.Day5Tue", "$.Day5Wed", "$.Day5Thu", "$.Day5Fri", "$.Day5Sat", "$.Day5Sun"] },
        "start": "$.Start_x0020_Time_x0020_5", "end": "$.End_x0020_Time_x0020_5",
        "location": { "join": ["$.Building_x0020_5", "$.Room_x0020_5"] },
        "start_date": "$.Start_x0020_Date_x0020_5", "end_date": "$.End_x0020_Date_x0020_5" },
      { "days": { "flags": ["$.Day6Mon", "$.Day6Tue", "$.Day6Wed", "$.Day6Thu", "$.Day6Fri", "$.Day6Sat", "$.Day6Sun"] },
        "start": "$.Start_x0020_Time_x0020_6", "end": "$.End_x0020_Time_x0020_6",
        "location": { "join": ["$.Building_x0020_6", "$.Room_x0020_6"] },
        "start_date": "$.Start_x0020_Date_x0020_6", "end_date": "$.End_x0020_Date_x0020_6" }
    ]
  }
}
```

- [ ] **Step 5: Write the Norco and Moreno Valley specs**

Copy `78.json` to `148.json` and `149.json` byte for byte, then change exactly these values in each:

`src/schedule/data/specs/148.json`:
- `"cc_id": 148`
- `"cc_name": "Norco College"`
- `"url": "https://apps-studentrcc.msappproxy.net/schedule/_api/web/lists/getByTitle('ScheduleData_NOR')/items"`

`src/schedule/data/specs/149.json`:
- `"cc_id": 149`
- `"cc_name": "Moreno Valley College"`
- `"url": "https://apps-studentrcc.msappproxy.net/schedule/_api/web/lists/getByTitle('ScheduleData_MOV')/items"`

Everything else (probe, inputs, `$select`, extract) stays identical; the three campuses share one schema. Verify with `diff src/schedule/data/specs/78.json src/schedule/data/specs/148.json` — exactly three changed lines.

- [ ] **Step 6: Add the catalog entries**

Append to the array in `src/schedule/data/colleges.json` (keep the file's existing one-entry-per-block style):

```json
  {"cc_id": 78, "cc_name": "Riverside City College", "system": "replay",
   "base_url": "https://apps-studentrcc.msappproxy.net", "locations": [],
   "source_url": "https://www.rcc.edu/admissions/schedule-of-classes.html",
   "provenance": {"method": "manual", "verified_at": "2026-09-23", "probe_course": "MATH-C2220"},
   "note": "Replay spec 78.json (RCCD Class Finder OData). ASSIST codes (MAT 1B) predate common course numbering (MATH-C2220); exact lookups return no rows until Phase 3 aliases."},
  {"cc_id": 148, "cc_name": "Norco College", "system": "replay",
   "base_url": "https://apps-studentrcc.msappproxy.net", "locations": [],
   "source_url": "https://www.norcocollege.edu/admissions/schedule/index.html",
   "provenance": {"method": "manual", "verified_at": "2026-09-23", "probe_course": "MATH-C2220"},
   "note": "Replay spec 148.json (RCCD Class Finder OData, list ScheduleData_NOR). Same numbering caveat as Riverside City College."},
  {"cc_id": 149, "cc_name": "Moreno Valley College", "system": "replay",
   "base_url": "https://apps-studentrcc.msappproxy.net", "locations": [],
   "source_url": "https://www.mvc.edu/admissions/schedule-of-classes.html",
   "provenance": {"method": "manual", "verified_at": "2026-09-23", "probe_course": "MATH-C2220"},
   "note": "Replay spec 149.json (RCCD Class Finder OData, list ScheduleData_MOV). Same numbering caveat as Riverside City College."}
```

`cc_name` values must match the ASSIST rows exactly (`sqlite3 data/assist.sqlite3 "select distinct cc_id, cc_name from articulation_rows where cc_id in (78,148,149)"` prints `Riverside City College`, `Norco College`, `Moreno Valley College`). The catalog loader ignores `note` and `provenance`; the registry test checks names.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_specs_registry.py tests/schedule/replay/test_specs_rccd.py tests/schedule/test_catalog.py -q`
Expected: all PASS (`test_get_college_source_all_entries` and `test_find_by_name_all_entries` in `test_catalog.py` are parametrized over every entry and now cover the three new ones).

- [ ] **Step 8: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add src/schedule/data/specs/78.json src/schedule/data/specs/148.json src/schedule/data/specs/149.json src/schedule/data/colleges.json tests/fixtures/replay/rccd_riv_sample.json tests/schedule/replay/test_specs_registry.py tests/schedule/replay/test_specs_rccd.py
git commit -m "feat(catalog): add Riverside, Norco, and Moreno Valley via replay specs"
```

---

### Task 9: NOCCCD specs (Cypress, Fullerton)

Portal facts (verified live 2026-09-23): `https://schedule.nocccd.edu/data/terms.json` lists `[{"termCode":"202620","termDesc":"Winter/Spring 2027"},{"termCode":"202615","termDesc":"NOCE Fall 2026"},{"termCode":"202610","termDesc":"Fall 2026"}]`. `https://schedule.nocccd.edu/data/{termCode}/sections.json` is one array of every section in the district (3,927 rows, a few MB) with `sectCampCode` `"1"` = Cypress, `"2"` = Fullerton (`/data/{termCode}/campus.json`). Course numbers carry a campus letter: Cypress `150AC`, `009 C`; Fullerton `151 F`, `100 F`. ASSIST spells Cypress codes inconsistently (`MATH 150AC` but `CSCI 123`), so the filter accepts `{number}` and `{number}C` (Cypress) or `{number}F` (Fullerton). Meetings are `sectMeetings[]` with `monDay: "M"`-style keys present only on meeting days, `beginTime`/`endTime` as `HHMM`, `bldgCode` `ONLINE`/`ZOOM` for remote, and `schdDesc` wording (`Lecture`, `Online`, `Hybrid`). No title field exists in `sections.json`; titles live in `courses.json`, which this phase does not join, so `title` is a constant empty string.

**Files:**
- Create: `src/schedule/data/specs/71.json`, `src/schedule/data/specs/134.json`
- Create: `tests/fixtures/replay/nocccd_terms.json`, `tests/fixtures/replay/nocccd_sections_sample.json`
- Modify: `src/schedule/data/colleges.json`
- Test: `tests/schedule/replay/test_specs_nocccd.py`

**Interfaces:**
- Consumes: Tasks 1–8 (registry integrity test now covers these two entries).
- Produces: two loadable specs, two catalog entries.

- [ ] **Step 1: Write the fixtures**

Create `tests/fixtures/replay/nocccd_terms.json` (verbatim from the portal):

```json
[{"termCode":"202620","termDesc":"Winter/Spring 2027"},{"termCode":"202615","termDesc":"NOCE Fall 2026"},{"termCode":"202610","termDesc":"Fall 2026"}]
```

Create `tests/fixtures/replay/nocccd_sections_sample.json` (five real rows, trimmed to the keys the spec reads plus `sectSstsCode`):

```json
[
 {"sectKey": "20261010444", "sectTermCode": "202610", "sectSubjCode": "MATH", "sectCrseNumb": "150AC", "sectCrn": "10444",
  "sectSchdCode": "02", "sectInsmCode": "02", "sectSstsCode": "A", "sectMaxEnrl": 35, "sectEnrl": 32, "sectSeatsAvail": 3,
  "sectWaitCount": 0, "sectWaitCapacity": 20, "sectCampCode": "1", "sectInstrName": "Shihabi, Azzam",
  "sectMeetings": [
   {"beginTime": "0815", "endTime": "1020", "tueDay": "T", "thuDay": "R", "bldgCode": "SEM", "bldgDesc": "Bldg #35 - CC-Science-Eng-Math",
    "roomCode": "304", "startDate": "08/24/2026", "endDate": "12/12/2026", "mtypCode": "CLAS", "schdCode": "02", "schdDesc": "Lecture",
    "meetInstrName": "Shihabi, Azzam"}]},
 {"sectKey": "20261010434", "sectTermCode": "202610", "sectSubjCode": "MATH", "sectCrseNumb": "011 C", "sectCrn": "10434",
  "sectSchdCode": "HY", "sectInsmCode": "HYA", "sectSstsCode": "A", "sectMaxEnrl": 30, "sectEnrl": 26, "sectSeatsAvail": 4,
  "sectWaitCount": 0, "sectWaitCapacity": 20, "sectCampCode": "1", "sectInstrName": "Trevino, Joseph",
  "sectMeetings": [
   {"beginTime": "1615", "endTime": "1705", "tueDay": "T", "bldgCode": "SEM", "bldgDesc": "Bldg #35 - CC-Science-Eng-Math",
    "roomCode": "203", "startDate": "08/24/2026", "endDate": "12/12/2026", "mtypCode": "CLAS", "schdCode": "02", "schdDesc": "Lecture",
    "meetInstrName": "Trevino, Joseph"},
   {"bldgCode": "ONLINE", "bldgDesc": "ONLINE", "startDate": "08/24/2026", "endDate": "12/12/2026", "mtypCode": "HY",
    "schdCode": "HY", "schdDesc": "Hybrid", "meetInstrName": "Trevino, Joseph"}]},
 {"sectKey": "20261012493", "sectTermCode": "202610", "sectSubjCode": "MATH", "sectCrseNumb": "100 F", "sectCrn": "12493",
  "sectSchdCode": "72", "sectInsmCode": "72", "sectSstsCode": "A", "sectMaxEnrl": 35, "sectEnrl": 32, "sectSeatsAvail": 3,
  "sectWaitCount": 0, "sectWaitCapacity": 10, "sectCampCode": "2", "sectInstrName": "Klassen, Kelly",
  "sectMeetings": [
   {"bldgCode": "ONLINE", "bldgDesc": "ONLINE", "roomCode": "ONLINE", "startDate": "08/24/2026", "endDate": "12/12/2026",
    "mtypCode": "ONL", "schdCode": "72", "schdDesc": "Online", "meetInstrName": "Klassen, Kelly"}]},
 {"sectKey": "20261012522", "sectTermCode": "202610", "sectSubjCode": "MATH", "sectCrseNumb": "151 F", "sectCrn": "12522",
  "sectSchdCode": "02", "sectInsmCode": "02", "sectSstsCode": "A", "sectMaxEnrl": 30, "sectEnrl": 26, "sectSeatsAvail": 4,
  "sectWaitCount": 0, "sectWaitCapacity": 10, "sectCampCode": "2", "sectInstrName": "Hoang, Thanh",
  "sectMeetings": [
   {"beginTime": "0715", "endTime": "0920", "monDay": "M", "wedDay": "W", "bldgCode": "2400", "bldgDesc": "2400", "roomCode": "206",
    "startDate": "08/24/2026", "endDate": "12/12/2026", "mtypCode": "CLAS", "schdCode": "02", "schdDesc": "Lecture",
    "meetInstrName": "Hoang, Thanh"}]},
 {"sectKey": "20261012523", "sectTermCode": "202610", "sectSubjCode": "MATH", "sectCrseNumb": "151 F", "sectCrn": "12523",
  "sectSchdCode": "02", "sectInsmCode": "02", "sectSstsCode": "A", "sectMaxEnrl": 30, "sectEnrl": 25, "sectSeatsAvail": 5,
  "sectWaitCount": 0, "sectWaitCapacity": 10, "sectCampCode": "2", "sectInstrName": "Romero Hernandez, Abraham",
  "sectMeetings": [
   {"beginTime": "0815", "endTime": "1020", "tueDay": "T", "thuDay": "R", "bldgCode": "2400", "bldgDesc": "2400", "roomCode": "206",
    "startDate": "08/24/2026", "endDate": "12/12/2026", "mtypCode": "CLAS", "schdCode": "02", "schdDesc": "Lecture",
    "meetInstrName": "Romero Hernandez, Abraham"}]}
]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/schedule/replay/test_specs_nocccd.py`:

```python
"""NOCCCD specs (71 Cypress, 134 Fullerton) against recorded terms.json and sections.json samples."""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from src.schedule.catalog import get_college_source
from src.schedule.generic_replay import GenericReplayProvider
from src.schedule.replay.executor import HostThrottle, ReplayExecutor
from src.schedule.term import TermNotListedError, parse_term_label

from .fakes import FakeSession

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "replay"
_TERMS_URL = "https://schedule.nocccd.edu/data/terms.json"
_FALL_SECTIONS_URL = "https://schedule.nocccd.edu/data/202610/sections.json"
_SPRING_SECTIONS_URL = "https://schedule.nocccd.edu/data/202620/sections.json"


def _session() -> FakeSession:
    return FakeSession({
        _TERMS_URL: (_FIXTURES / "nocccd_terms.json").read_text(),
        _FALL_SECTIONS_URL: (_FIXTURES / "nocccd_sections_sample.json").read_text(),
        _SPRING_SECTIONS_URL: "[]",
    })


def _provider(session: FakeSession) -> GenericReplayProvider:
    return GenericReplayProvider(
        executor=ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None))


def _search(cc_id: int, course_code: str, label: str = "Fall 2026", session: FakeSession | None = None):
    session = session or _session()
    out = _provider(session).search_course(
        source=get_college_source(cc_id), term=parse_term_label(label), course_code=course_code)
    return out, session


def test_cypress_exact_code_with_campus_suffix():
    out, session = _search(71, "MATH 150AC")
    assert [c["url"] for c in session.calls] == [_TERMS_URL, _FALL_SECTIONS_URL]
    assert out.offered is True and [s.section_id for s in out.sections] == ["10444"]
    section = out.sections[0]
    assert section.course_code_as_listed == "MATH 150AC" and section.title == ""
    assert section.instructor == "Shihabi, Azzam"
    assert section.seats_total == 35 and section.seats_used == 32 and section.status == "open"
    assert section.modality == "in_person"
    meeting = section.meetings[0]
    assert meeting.days == ("T", "R") and meeting.start_local == time(8, 15) and meeting.end_local == time(10, 20)
    assert meeting.location == "SEM 304" and meeting.is_online is False
    assert meeting.start_date == date(2026, 8, 24) and meeting.end_date == date(2026, 12, 12)


def test_cypress_code_without_suffix_matches_padded_number():
    out, _ = _search(71, "MATH 11")
    assert [s.section_id for s in out.sections] == ["10434"]
    assert out.sections[0].modality == "hybrid"
    assert [m.is_online for m in out.sections[0].meetings] == [False, True]


def test_cypress_does_not_see_fullerton_rows():
    out, _ = _search(71, "MATH 151")
    assert out.offered is False


def test_fullerton_in_person_rows():
    out, _ = _search(134, "MATH 151")
    assert [s.section_id for s in out.sections] == ["12522", "12523"]
    assert out.sections[0].meetings[0].days == ("M", "W")
    assert out.sections[0].course_code_as_listed == "MATH 151 F"


def test_fullerton_online_row():
    out, _ = _search(134, "MATH 100")
    assert [s.section_id for s in out.sections] == ["12493"]
    section = out.sections[0]
    assert section.modality == "async_online"
    assert section.meetings[0].is_online is True and section.meetings[0].start_local is None


def test_sections_file_is_fetched_once_per_college_search():
    session = _session()
    _search(134, "MATH 151", session=session)
    provider = _provider(session)
    for code in ("MATH 151", "MATH 100", "CSCI 123"):
        provider.search_course(source=get_college_source(134), term=parse_term_label("Fall 2026"), course_code=code)
    urls = [c["url"] for c in session.calls]
    assert urls.count(_TERMS_URL) == 2 and urls.count(_FALL_SECTIONS_URL) == 2  # one per provider instance


def test_spring_term_resolves_by_season_and_year():
    out, session = _search(134, "MATH 151", label="Spring 2027")
    assert session.calls[1]["url"] == _SPRING_SECTIONS_URL
    assert out.offered is False


def test_unlisted_term_is_term_not_listed():
    with pytest.raises(TermNotListedError, match="Summer 2027"):
        _search(134, "MATH 151", label="Summer 2027")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_specs_nocccd.py -q`
Expected: FAIL with `KeyError: 'No schedule source configured for cc_id=71'`.

- [ ] **Step 4: Write the Cypress spec**

Create `src/schedule/data/specs/71.json`:

```json
{
  "cc_id": 71,
  "cc_name": "Cypress College",
  "version": 1,
  "recorded_at": "2026-09-23",
  "notes": "NOCCCD static JSON. terms.json maps labels to term codes (202610 = Fall 2026, 202620 = Winter/Spring 2027). sections.json is the whole district for the term; filter on sectCampCode 1 (Cypress) and a course number that may carry the campus letter C (150AC, 009 C). Titles are not in sections.json.",
  "probe": { "course_code": "MATH 150AC", "term": "Fall 2026", "expect_min_rows": 1 },
  "inputs": {},
  "steps": [
    {
      "id": "terms",
      "method": "GET",
      "url": "https://schedule.nocccd.edu/data/terms.json",
      "cache": true,
      "captures": {
        "term": { "lookup": { "rows": "$[*]", "label": "$.termDesc", "value": "$.termCode" }, "on_missing": "term_not_listed" }
      }
    },
    {
      "id": "sections",
      "method": "GET",
      "url": "https://schedule.nocccd.edu/data/{term}/sections.json",
      "cache": true
    }
  ],
  "extract": {
    "kind": "json",
    "rows": "$[*]",
    "filter": [
      { "value": "$.sectCampCode", "equals": "1" },
      { "value": "$.sectSubjCode", "equals": "{subject}" },
      { "value": "$.sectCrseNumb", "any_of": ["{number}", "{number}C"] }
    ],
    "fields": {
      "section_id": "$.sectCrn",
      "title": { "const": "" },
      "instructor": "$.sectInstrName",
      "seats_total": "$.sectMaxEnrl",
      "seats_used": "$.sectEnrl",
      "seats_available": "$.sectSeatsAvail",
      "wait_capacity": "$.sectWaitCapacity",
      "course_code_as_listed": { "join": ["$.sectSubjCode", "$.sectCrseNumb"] }
    },
    "status": { "from_seats": true },
    "modality": { "tokens": ["$.sectMeetings[*].schdDesc"] },
    "meetings": [
      {
        "each": "$.sectMeetings[*]",
        "days": { "flags": ["$.monDay", "$.tueDay", "$.wedDay", "$.thuDay", "$.friDay", "$.satDay", "$.sunDay"] },
        "start": "$.beginTime",
        "end": "$.endTime",
        "location": { "join": ["$.bldgCode", "$.roomCode"] },
        "start_date": "$.startDate",
        "end_date": "$.endDate"
      }
    ]
  }
}
```

- [ ] **Step 5: Write the Fullerton spec**

Copy `71.json` to `src/schedule/data/specs/134.json` and change exactly these values:
- `"cc_id": 134`
- `"cc_name": "Fullerton College"`
- in `notes`, replace `sectCampCode 1 (Cypress) and a course number that may carry the campus letter C (150AC, 009 C)` with `sectCampCode 2 (Fullerton) and a course number that may carry the campus letter F (151 F, 100 F)`
- `"probe": { "course_code": "MATH 151", "term": "Fall 2026", "expect_min_rows": 1 }`
- first filter: `{ "value": "$.sectCampCode", "equals": "2" }`
- third filter: `{ "value": "$.sectCrseNumb", "any_of": ["{number}", "{number}F"] }`

`diff src/schedule/data/specs/71.json src/schedule/data/specs/134.json` must show exactly those six changed lines.

- [ ] **Step 6: Add the catalog entries**

Append to `src/schedule/data/colleges.json`:

```json
  {"cc_id": 71, "cc_name": "Cypress College", "system": "replay",
   "base_url": "https://schedule.nocccd.edu", "locations": [],
   "source_url": "https://schedule.nocccd.edu/?college=1",
   "provenance": {"method": "manual", "verified_at": "2026-09-23", "probe_course": "MATH 150AC"},
   "note": "Replay spec 71.json (NOCCCD static JSON, sectCampCode 1). Section titles are not available."},
  {"cc_id": 134, "cc_name": "Fullerton College", "system": "replay",
   "base_url": "https://schedule.nocccd.edu", "locations": [],
   "source_url": "https://schedule.nocccd.edu/?college=2",
   "provenance": {"method": "manual", "verified_at": "2026-09-23", "probe_course": "MATH 151"},
   "note": "Replay spec 134.json (NOCCCD static JSON, sectCampCode 2). Section titles are not available."}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_specs_nocccd.py tests/schedule/replay/test_specs_registry.py -q`
Expected: all PASS.

- [ ] **Step 8: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add src/schedule/data/specs/71.json src/schedule/data/specs/134.json src/schedule/data/colleges.json tests/fixtures/replay/nocccd_terms.json tests/fixtures/replay/nocccd_sections_sample.json tests/schedule/replay/test_specs_nocccd.py
git commit -m "feat(catalog): add Cypress and Fullerton via NOCCCD replay specs"
```

---

### Task 10: Los Rios specs (American River, Cosumnes River, Folsom Lake, Sacramento City)

Portal facts (verified live 2026-09-23): `GET https://hub.losrios.edu/classSearch/getCourses.php` with `arcFilter=true` (or `crcFilter`/`flcFilter`/`sccFilter`), `subjectFilters=MATH`, `searchBar=MATH 400`, `strm=1269`, `href=arc`, `offset=0`, `first=1` returns an HTML fragment: a `div.filter-results` header with `<span id='totalResults'>15</span>` and `article.class-card` blocks. The server pages 20 cards at a time and `offset` is a page index (offset=1 is the second page); `limit`/`first` do not change the page size. The term code `strm` comes from `https://losrios.edu/academics/search-class-schedules`, which renders `<label class="search-filter-label" for="1269">Fall 2026`. A zero-result search still renders the header with `totalResults` 0. Cards show `Mode` (`In Person`, `Fully Online`, `Partially Online`), `Day/Time` (`Mon/Wed, 3:00 pm to 5:20 pm` or `Asynchronous – no scheduled meeting times`), `Building`, `Instructor`, and `li.status` (`Closed`, `Open`, `Waitlist`). No seat counts. The `searchBar` match is a SQL `LIKE '%400%'`, so the spec filters cards on the exact course code client-side.

**Files:**
- Create: `src/schedule/data/specs/27.json`, `142.json`, `145.json`, `126.json`
- Create: `tests/fixtures/replay/losrios_terms_page.html`, `tests/fixtures/replay/losrios_arc_math_cards.html`
- Modify: `src/schedule/data/colleges.json`
- Test: `tests/schedule/replay/test_specs_losrios.py`

**Interfaces:**
- Consumes: Tasks 1–9.
- Produces: four loadable HTML specs, four catalog entries.

- [ ] **Step 1: Write the fixtures**

Create `tests/fixtures/replay/losrios_terms_page.html` (the two lines of the real page that matter, plus a decoy):

```html
<html><body>
<div class="search-filters">
<input type="radio" name="strm" id="1269" value="1269"><label class="search-filter-label" for="1269">Fall 2026</label>
<input type="radio" name="strm" id="UCS" value="UCS"><label class='search-filter-label' for='UCS'>UCD - Spring</label>
</div>
</body></html>
```

Create `tests/fixtures/replay/losrios_arc_math_cards.html` (real header and three real cards from two searches on 2026-09-23: MATH 400 sections 10414 and 10413, and a MATH 300 fully-online section 12286; whitespace and comments kept as served):

```html
<!-- session STRM_sgt 1273-->
			<div class='filter-results'>
				<h2 class='border-bottom'> Class Search Results<!-- **--></h2>

				<div>
					<p>Class availability accurate as of 05:25:23 PM PST.</p><p class='results-num'><span id='totalResults' style='display:inline-block;'>3</span> results for:</p></div>
				
				<ul><li><a href='javascript:void();' rel='nofollow' onclick='clearLocation("arcFilter","ARC");return false; buttonNameUpdate("campus");' class='filter-result'>ARC<i class='fa fa-times-circle' aria-hidden='true'></i></a></li><li><a href='javascript:void();' rel='nofollow' onclick='clearSubject("MATH","MATH");return false;' class='filter-result'>MATH<i class='fa fa-times-circle' aria-hidden='true'></i></a></li><li><a href='javascript:void();' rel='nofollow' onclick='clearAll();' class='filter-result  clear-results-filter'>Clear All Filters</a></li>
				</ul>
			</div><ul class='class-cards'><!--  -->
<li>
	<article class="class-card" id="">
		<div class="info">
			<div class="heading">
				<div class="title">
					<span class="class-card-subj-num">
					MATH 400</span> Calculus I				</div>
				<div class="data-bubbles">
										<div class="units">
						<span>
							5 units
						</span>
					</div>
				</div>
				<div class="location">
					<span class="college">
					American River College					</span>
					<span class='campus'>Main Campus</span>				</div>
				<div class="session">
				Full Term (August 22 to December 17)				<!-- <br> -->
				</div>
			</div>
			<div class="details">
				<div class='detail sec-single'><ul>
	<li class="section">
	<span class="label">Class</span>
	LEC&nbsp;10414	</li>
	<li style="min-width:103px;">
		<span class="label">Mode</span>
		In Person	
	</li>
		<li><span class='label'>Day/Time</span>Mon/Wed, 3:00 pm to 5:20 pm</li>		
	<li><span class='label'>Building<!-- 1 --></span>Main Campus, 
STEM
, 310</li>	
		<li><span class='label'>Instructor</span><a href="https://arc.losrios.edu/about-us/contact-us/employee-directory/employee?xid=x79582&id=1277636" target="_blank" class="modalLink extLink">Karsten Stemmann</a></li>	
	<li class="status">
		 <span class='highlight highlight--closed'></span>Closed
	</li>
</ul></div>			</div>
			<!-- 	no preCCN -->		</div>
		<div class="links">
			<a class="more-info" href="javascript:void(0);" onClick="getModal('004006','201','ARC','1269|10414');">
				<span class="sr-only">
					More information about MATH 400 Calculus I 				</span>
				<span>
					<i class="fa fa-arrow-right" aria-hidden="true"></i>
				</span>
			</a>
		</div>
	</article>
</li><!--  -->
<li>
	<article class="class-card" id="">
		<div class="info">
			<div class="heading">
				<div class="title">
					<span class="class-card-subj-num">
					MATH 400</span> Calculus I				</div>
				<div class="data-bubbles">
										<div class="units">
						<span>
							5 units
						</span>
					</div>
				</div>
				<div class="location">
					<span class="college">
					American River College					</span>
					<span class='campus'>Main Campus</span>				</div>
				<div class="session">
				Full Term (August 22 to December 17)				<!-- <br> -->
				</div>
			</div>
			<div class="details">
				<div class='detail sec-single'><ul>
	<li class="section">
	<span class="label">Class</span>
	LEC&nbsp;10413	</li>
	<li style="min-width:103px;">
		<span class="label">Mode</span>
		In Person	
	</li>
		<li><span class='label'>Day/Time</span>Mon/Wed, 8:00 am to 10:20 am</li>		
	<li><span class='label'>Building<!-- 1 --></span>Main Campus, 
STEM
, 310</li>	
		<li><span class='label'>Instructor</span><a href="https://arc.losrios.edu/about-us/contact-us/employee-directory/employee?xid=x77574&id=0341377" target="_blank" class="modalLink extLink">Christopher P. Heeren</a></li>	
	<li class="status">
		 <span class='highlight highlight--closed'></span>Closed
	</li>
</ul></div>			</div>
			<!-- 	no preCCN -->		</div>
		<div class="links">
			<a class="more-info" href="javascript:void(0);" onClick="getModal('004006','203','ARC','1269|10413');">
				<span class="sr-only">
					More information about MATH 400 Calculus I 				</span>
				<span>
					<i class="fa fa-arrow-right" aria-hidden="true"></i>
				</span>
			</a>
		</div>
	</article>
</li><!--  -->
<li>
	<article class="class-card" id="">
		<div class="info">
			<div class="heading">
				<div class="title">
					<span class="class-card-subj-num">
					MATH 300</span> Introduction to Mathematical Ideas &#8211; MATH300/MATHS95 Linked Section				</div>
				<div class="data-bubbles">
										<div class="units">
						<span>
							3 units
						</span>
					</div>
				</div>
				<div class="location">
					<span class="college">
					American River College					</span>
									</div>
				<div class="session">
				Full Term (August 22 to December 17)				<!-- <br> -->
				</div>
			</div>
			<div class="details">
				<div class='detail sec-single'><ul>
	<li class="section">
	<span class="label">Class</span>
	LEC&nbsp;12286	</li>
	<li style="min-width:103px;">
		<span class="label">Mode</span>
		Fully Online	
	</li>
		<li><span class='label'>Day/Time</span>Asynchronous – no scheduled meeting times<!-- Hello world. --></li>		
		<li><span class='label'>Instructor</span><a href="https://arc.losrios.edu/about-us/contact-us/employee-directory/employee?xid=x76097&id=1449536" target="_blank" class="modalLink extLink">Trisha R. Butler</a></li>	
	<li class="status">
		 <span class='highlight highlight--closed'></span>Closed
	</li>
</ul></div>			</div>
			<!-- 	no preCCN -->		</div>
		<div class="links">
			<a class="more-info" href="javascript:void(0);" onClick="getModal('003981','602','ARC','1269|12286');">
				<span class="sr-only">
					More information about MATH 300 Introduction to Mathematical Ideas 				</span>
				<span>
					<i class="fa fa-arrow-right" aria-hidden="true"></i>
				</span>
			</a>
		</div>
	</article>
</li></ul>
```

- [ ] **Step 2: Write the failing tests**

Create `tests/schedule/replay/test_specs_losrios.py`:

```python
"""Los Rios specs (27 ARC, 142 CRC, 145 FLC, 126 SCC) against recorded HTML samples."""
from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from src.schedule.catalog import get_college_source
from src.schedule.errors import PortalChanged
from src.schedule.generic_replay import GenericReplayProvider
from src.schedule.replay.executor import HostThrottle, ReplayExecutor
from src.schedule.term import TermNotListedError, parse_term_label

from .fakes import FakeSession

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "replay"
_TERMS_URL = "https://losrios.edu/academics/search-class-schedules"
_SEARCH_URL = "https://hub.losrios.edu/classSearch/getCourses.php"


def _session(cards: str | None = None) -> FakeSession:
    return FakeSession({
        _TERMS_URL: (_FIXTURES / "losrios_terms_page.html").read_text(),
        _SEARCH_URL: cards if cards is not None else (_FIXTURES / "losrios_arc_math_cards.html").read_text(),
    })


def _provider(session: FakeSession) -> GenericReplayProvider:
    return GenericReplayProvider(
        executor=ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None))


def _search(cc_id: int, course_code: str, label: str = "Fall 2026", session: FakeSession | None = None):
    session = session or _session()
    out = _provider(session).search_course(
        source=get_college_source(cc_id), term=parse_term_label(label), course_code=course_code)
    return out, session


@pytest.mark.parametrize("cc_id,flag,href", [
    (27, "arcFilter", "arc"), (142, "crcFilter", "crc"), (145, "flcFilter", "flc"), (126, "sccFilter", "scc"),
])
def test_request_shape_per_college(cc_id: int, flag: str, href: str):
    _, session = _search(cc_id, "MATH 400")
    assert session.calls[0]["url"] == _TERMS_URL
    params = session.calls[1]["params"]
    assert session.calls[1]["url"] == _SEARCH_URL
    assert params[flag] == "true" and params["href"] == href
    assert {k for k, v in params.items() if k.endswith("Filter") and v == "true"} == {flag}
    assert params["subjectFilters"] == "MATH" and params["searchBar"] == "MATH 400"
    assert params["strm"] == "1269" and params["offset"] == "0" and params["first"] == "1"


def test_arc_math_400_sections():
    out, _ = _search(27, "MATH 400")
    assert out.offered is True
    assert [s.section_id for s in out.sections] == ["10414", "10413"]
    first = out.sections[0]
    assert first.title == "Calculus I" and first.course_code_as_listed == "MATH 400"
    assert first.instructor == "Karsten Stemmann" and first.status == "closed"
    assert first.modality == "in_person" and first.seats_total is None
    meeting = first.meetings[0]
    assert meeting.days == ("M", "W") and meeting.start_local == time(15, 0) and meeting.end_local == time(17, 20)
    assert meeting.location == "Main Campus, STEM , 310" and meeting.is_online is False
    assert out.sections[1].meetings[0].start_local == time(8, 0)


def test_arc_math_300_online_section_filtered_by_code():
    out, _ = _search(27, "MATH 300")
    assert [s.section_id for s in out.sections] == ["12286"]
    section = out.sections[0]
    assert section.modality == "async_online" and section.meetings == ()
    assert section.instructor == "Trisha R. Butler"


def test_other_college_cards_are_filtered_out():
    out, _ = _search(142, "MATH 400")  # cards say "American River College"
    assert out.offered is False and out.sections == []


def test_zero_results_page_is_not_offered():
    page = "<div class='filter-results'><span id='totalResults' style='display:inline-block;'>0</span></div><ul class='class-cards'></ul>"
    out, _ = _search(27, "MATH 9999", session=_session(cards=page))
    assert out.offered is False


def test_page_without_marker_is_portal_changed():
    with pytest.raises(PortalChanged, match="marker"):
        _search(27, "MATH 400", session=_session(cards="<html><body>Down for maintenance</body></html>"))


def test_pagination_requests_second_page_when_total_exceeds_20():
    cards = (_FIXTURES / "losrios_arc_math_cards.html").read_text().replace(
        "display:inline-block;'>3<", "display:inline-block;'>28<")
    out, session = _search(27, "MATH 400", session=_session(cards=cards))
    search_calls = [c for c in session.calls if c["url"] == _SEARCH_URL]
    assert [c["params"]["offset"] for c in search_calls] == ["0", "1"]
    assert len(out.sections) == 4  # both fake pages carry the same two MATH 400 cards


def test_terms_page_is_cached_across_courses():
    session = _session()
    provider = _provider(session)
    for code in ("MATH 400", "MATH 401"):
        provider.search_course(source=get_college_source(27), term=parse_term_label("Fall 2026"), course_code=code)
    assert [c["url"] for c in session.calls].count(_TERMS_URL) == 1


def test_unlisted_term_is_term_not_listed():
    with pytest.raises(TermNotListedError, match="Summer 2027"):
        _search(27, "MATH 400", label="Summer 2027")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_specs_losrios.py -q`
Expected: FAIL with `KeyError: 'No schedule source configured for cc_id=27'`.

- [ ] **Step 4: Write the American River College spec**

Create `src/schedule/data/specs/27.json`:

```json
{
  "cc_id": 27,
  "cc_name": "American River College",
  "version": 1,
  "recorded_at": "2026-09-23",
  "notes": "Los Rios district class search (hub.losrios.edu), shared by ARC/CRC/FLC/SCC via boolean filter flags. Term code (PeopleSoft strm, e.g. 1269 = Fall 2026) is read from the losrios.edu search page labels. Results page 20 cards at a time; offset is a page index. No seat counts on cards.",
  "probe": { "course_code": "MATH 400", "term": "Fall 2026", "expect_min_rows": 1 },
  "inputs": {},
  "steps": [
    {
      "id": "terms",
      "method": "GET",
      "url": "https://losrios.edu/academics/search-class-schedules",
      "cache": true,
      "captures": {
        "term": { "regex": "for=[\"'](\\d+)[\"']>\\s*{term_label}\\b", "on_missing": "term_not_listed" }
      }
    },
    {
      "id": "search",
      "method": "GET",
      "url": "https://hub.losrios.edu/classSearch/getCourses.php",
      "query": {
        "arcFilter": "true",
        "crcFilter": "false",
        "flcFilter": "false",
        "sccFilter": "false",
        "subjectFilters": "{subject}",
        "searchBar": "{subject} {number}",
        "strm": "{term}",
        "href": "arc",
        "offset": "0",
        "first": "1"
      },
      "captures": { "total": { "css": "#totalResults" } },
      "paginate": { "param": "offset", "first": 0, "increment": 1, "page_size": 20, "max_pages": 10, "total_capture": "total" }
    }
  ],
  "extract": {
    "kind": "html",
    "marker": "div.filter-results",
    "rows": "article.class-card",
    "filter": [
      { "value": "span.class-card-subj-num", "equals": "{subject} {number}" },
      { "value": "span.college", "equals": "American River College" }
    ],
    "fields": {
      "section_id": { "css": "li.section", "regex": "(\\d+)\\s*$" },
      "title": { "css": "div.title", "regex": "^[A-Z]+ [A-Z0-9]+\\s+(.+)$" },
      "instructor": { "css": "li:has(> span.label:-soup-contains('Instructor'))", "regex": "^Instructor\\s*(.*)$" },
      "course_code_as_listed": "span.class-card-subj-num"
    },
    "status": "li.status",
    "modality": {
      "tokens": [ { "css": "li:has(> span.label:-soup-contains('Mode'))", "regex": "^Mode\\s*(.*)$" } ],
      "map": { "partially online": "hybrid" }
    },
    "meetings": [
      {
        "time_text": "li:has(> span.label:-soup-contains('Day/Time'))",
        "time_pattern": "^Day/Time\\s*(?P<days>[A-Za-z/]+), (?P<start>\\d{1,2}:\\d{2} [ap]m) to (?P<end>\\d{1,2}:\\d{2} [ap]m)",
        "location": { "css": "li:has(> span.label:-soup-contains('Building'))", "regex": "^Building\\s*(.*)$" }
      }
    ]
  }
}
```

- [ ] **Step 5: Write the three sibling specs**

Copy `27.json` to `142.json`, `145.json`, and `126.json`, then change exactly these values:

`src/schedule/data/specs/142.json` (Cosumnes River College):
- `"cc_id": 142`, `"cc_name": "Cosumnes River College"`
- query: `"arcFilter": "false"`, `"crcFilter": "true"`, `"href": "crc"`
- second filter: `{ "value": "span.college", "equals": "Cosumnes River College" }`

`src/schedule/data/specs/145.json` (Folsom Lake College):
- `"cc_id": 145`, `"cc_name": "Folsom Lake College"`
- query: `"arcFilter": "false"`, `"flcFilter": "true"`, `"href": "flc"`
- second filter: `{ "value": "span.college", "equals": "Folsom Lake College" }`

`src/schedule/data/specs/126.json` (Sacramento City College):
- `"cc_id": 126`, `"cc_name": "Sacramento City College"`
- query: `"arcFilter": "false"`, `"sccFilter": "true"`, `"href": "scc"`
- second filter: `{ "value": "span.college", "equals": "Sacramento City College" }`

Each `diff` against `27.json` shows exactly six changed lines. Folsom Lake and Sacramento City were not probed in the survey; the live probe in Task 11 step 9 confirms them.

- [ ] **Step 6: Add the catalog entries**

Append to `src/schedule/data/colleges.json`:

```json
  {"cc_id": 27, "cc_name": "American River College", "system": "replay",
   "base_url": "https://hub.losrios.edu", "locations": [],
   "source_url": "https://losrios.edu/academics/search-class-schedules",
   "provenance": {"method": "manual", "verified_at": "2026-09-23", "probe_course": "MATH 400"},
   "note": "Replay spec 27.json (Los Rios district class search, arcFilter). Cards carry no seat counts."},
  {"cc_id": 142, "cc_name": "Cosumnes River College", "system": "replay",
   "base_url": "https://hub.losrios.edu", "locations": [],
   "source_url": "https://losrios.edu/academics/search-class-schedules",
   "provenance": {"method": "manual", "verified_at": "2026-09-23", "probe_course": "MATH 400"},
   "note": "Replay spec 142.json (Los Rios district class search, crcFilter). Cards carry no seat counts."},
  {"cc_id": 145, "cc_name": "Folsom Lake College", "system": "replay",
   "base_url": "https://hub.losrios.edu", "locations": [],
   "source_url": "https://losrios.edu/academics/search-class-schedules",
   "provenance": {"method": "manual", "verified_at": "2026-09-23", "probe_course": "MATH 400"},
   "note": "Replay spec 145.json (Los Rios district class search, flcFilter). Not probed in the survey; confirmed by the Phase 2 live probe."},
  {"cc_id": 126, "cc_name": "Sacramento City College", "system": "replay",
   "base_url": "https://hub.losrios.edu", "locations": [],
   "source_url": "https://losrios.edu/academics/search-class-schedules",
   "provenance": {"method": "manual", "verified_at": "2026-09-23", "probe_course": "MATH 400"},
   "note": "Replay spec 126.json (Los Rios district class search, sccFilter). Not probed in the survey; confirmed by the Phase 2 live probe."}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_specs_losrios.py tests/schedule/replay/test_specs_registry.py -q`
Expected: all PASS.

- [ ] **Step 8: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add src/schedule/data/specs/27.json src/schedule/data/specs/142.json src/schedule/data/specs/145.json src/schedule/data/specs/126.json src/schedule/data/colleges.json tests/fixtures/replay/losrios_terms_page.html tests/fixtures/replay/losrios_arc_math_cards.html tests/schedule/replay/test_specs_losrios.py
git commit -m "feat(catalog): add the four Los Rios colleges via HTML replay specs"
```

---

### Task 11: Replay CLI, docs, and live verification

**Files:**
- Create: `src/schedule/replay/cli.py`
- Test: `tests/schedule/replay/test_cli.py`
- Modify: `README.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: `registry.load_all_specs`, `registry.load_specs_from`, `generic_replay.GenericReplayProvider`, `catalog.get_college_source`, `schedule.cli._json_default`.
- Produces: `uv run python -m src.schedule.replay.cli validate` (exit 0 and a count, or exit 1 naming the bad file), `... run --cc-id N --term "Fall 2026" --course "MATH 400"` (JSON `CourseAvailability` on stdout), `... probe [--cc-id N]` (one PASS/FAIL line per spec using its `probe` block; exit 1 if any FAIL). This `probe` command is the seed of Phase 4's `revalidate`.

- [ ] **Step 1: Write the failing tests**

Create `tests/schedule/replay/test_cli.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest
from typer.testing import CliRunner

from src.schedule.models import CourseAvailability, ParsedSection
from src.schedule.replay import cli as replay_cli
from src.schedule.replay.spec import load_spec

runner = CliRunner()

_SPEC = {
    "cc_id": 78, "cc_name": "Riverside City College", "version": 1, "recorded_at": "2026-09-23",
    "probe": {"course_code": "MATH-C2220", "term": "Fall 2026", "expect_min_rows": 1},
    "inputs": {"term": {"format": "{yy}{SEASON}", "seasons": {"fall": "FAL"}}},
    "steps": [{"id": "s", "method": "GET", "url": "https://example.edu/api", "query": {"t": "{term}"}}],
    "extract": {"kind": "json", "rows": "$.value[*]", "fields": {"section_id": "$.id"}},
}


class _StubProvider:
    def __init__(self, sections_by_code: dict[str, int]) -> None:
        self._by_code = sections_by_code

    def supports_source(self, source) -> bool:
        return source.system == "replay"

    def search_course(self, *, source, term, course_code: str) -> CourseAvailability:
        count = self._by_code.get(course_code, 0)
        sections = [ParsedSection(section_id=str(i), status="open", modality="unknown", title="", instructor="")
                    for i in range(count)]
        return CourseAvailability(cc_id=source.cc_id, cc_name=source.cc_name, term=term.label,
                                  course_code=course_code, offered=bool(sections), sections=sections,
                                  source_url="https://example.edu/api", raw_summary="stub")


@pytest.fixture
def specs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "78.json"
    path.write_text(json.dumps(_SPEC))
    loaded = MappingProxyType({78: load_spec(path)})
    monkeypatch.setattr(replay_cli, "load_all_specs", lambda: loaded)
    return loaded


def test_validate_reports_count(specs):
    result = runner.invoke(replay_cli.app, ["validate"])
    assert result.exit_code == 0
    assert "1 spec(s) valid" in result.stdout


def test_validate_reports_bad_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "1.json").write_text("{}")
    monkeypatch.setattr(replay_cli, "SPECS_DIR", tmp_path)
    monkeypatch.setattr(replay_cli, "load_all_specs", lambda: replay_cli.load_specs_from(tmp_path))
    result = runner.invoke(replay_cli.app, ["validate"])
    assert result.exit_code == 1
    assert "1.json" in result.output


def test_run_prints_availability_json(specs, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(replay_cli, "_provider", lambda: _StubProvider({"MATH 1": 2}))
    result = runner.invoke(replay_cli.app, ["run", "--cc-id", "78", "--term", "Fall 2026", "--course", "MATH 1"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["offered"] is True and len(payload["sections"]) == 2


def test_run_unknown_cc_id_exits_2(specs):
    result = runner.invoke(replay_cli.app, ["run", "--cc-id", "1", "--term", "Fall 2026", "--course", "MATH 1"])
    assert result.exit_code == 2


def test_probe_pass_and_fail(specs, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(replay_cli, "_provider", lambda: _StubProvider({"MATH-C2220": 3}))
    ok = runner.invoke(replay_cli.app, ["probe"])
    assert ok.exit_code == 0 and "PASS 78 Riverside City College 3 row(s)" in ok.stdout

    monkeypatch.setattr(replay_cli, "_provider", lambda: _StubProvider({}))
    bad = runner.invoke(replay_cli.app, ["probe", "--cc-id", "78"])
    assert bad.exit_code == 1 and "FAIL 78 Riverside City College 0 row(s) (expected >= 1)" in bad.output


def test_probe_reports_exception_as_fail(specs, monkeypatch: pytest.MonkeyPatch):
    class _Boom(_StubProvider):
        def search_course(self, **kwargs):
            raise RuntimeError("kaboom")

    monkeypatch.setattr(replay_cli, "_provider", lambda: _Boom({}))
    result = runner.invoke(replay_cli.app, ["probe"])
    assert result.exit_code == 1 and "FAIL 78 Riverside City College RuntimeError: kaboom" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/schedule/replay/test_cli.py -q`
Expected: FAIL with `ImportError: cannot import name 'cli' from 'src.schedule.replay'`.

- [ ] **Step 3: Implement the CLI**

Create `src/schedule/replay/cli.py`:

```python
"""Manual tools for replay specs: validate them, run one live lookup, or probe each college.

    uv run python -m src.schedule.replay.cli validate
    uv run python -m src.schedule.replay.cli run --cc-id 27 --term "Fall 2026" --course "MATH 400"
    uv run python -m src.schedule.replay.cli probe [--cc-id 27]

``run`` and ``probe`` hit the live portals; they are for manual checks, not pytest.
"""
from __future__ import annotations

import json
from dataclasses import asdict

import typer

from ..catalog import get_college_source
from ..cli import _json_default
from ..errors import SpecInvalid
from ..generic_replay import GenericReplayProvider
from ..providers import ScheduleProvider
from ..term import parse_term_label
from .registry import SPECS_DIR, load_all_specs, load_specs_from

app = typer.Typer(help="Replay-spec tools: validate, run one lookup, or probe every college.")


def _provider() -> ScheduleProvider:
    return GenericReplayProvider()


@app.callback()
def main() -> None:
    """Replay CLI command group."""


@app.command()
def validate() -> None:
    """Load every spec under src/schedule/data/specs and report the first invalid one."""
    try:
        specs = load_all_specs()
    except SpecInvalid as err:
        typer.echo(f"INVALID: {err}", err=True)
        raise typer.Exit(code=1) from err
    typer.echo(f"{len(specs)} spec(s) valid in {SPECS_DIR}")


@app.command()
def run(
    cc_id: int = typer.Option(..., help="Community college id with a replay spec."),
    term: str = typer.Option(..., help='Term label like "Fall 2026".'),
    course: str = typer.Option(..., help='Course code as ASSIST lists it, e.g. "MATH 400".'),
) -> None:
    """Run one live lookup through the college's replay spec and print the result as JSON."""
    if cc_id not in load_all_specs():
        raise typer.BadParameter(f"No replay spec for cc_id={cc_id}", param_hint="--cc-id")
    try:
        parsed_term = parse_term_label(term)
    except ValueError as err:
        raise typer.BadParameter(str(err), param_hint="--term") from err
    source = get_college_source(cc_id)
    out = _provider().search_course(source=source, term=parsed_term, course_code=course)
    typer.echo(json.dumps(asdict(out), indent=2, default=_json_default))


@app.command()
def probe(
    cc_id: int = typer.Option(0, help="Probe one college; 0 (default) probes every spec."),
) -> None:
    """Run each spec's recorded probe course and report PASS/FAIL per college."""
    specs = load_all_specs()
    if cc_id and cc_id not in specs:
        raise typer.BadParameter(f"No replay spec for cc_id={cc_id}", param_hint="--cc-id")
    targets = [specs[cc_id]] if cc_id else list(specs.values())
    provider = _provider()
    failures = 0
    for spec in targets:
        line = _probe_one(provider, spec)
        failures += line.startswith("FAIL")
        typer.echo(line)
    if failures:
        raise typer.Exit(code=1)


def _probe_one(provider: ScheduleProvider, spec) -> str:
    label = f"{spec.cc_id} {spec.cc_name}"
    try:
        out = provider.search_course(
            source=get_college_source(spec.cc_id),
            term=parse_term_label(spec.probe.term),
            course_code=spec.probe.course_code,
        )
    except Exception as err:  # a probe must report, not crash, so every college is listed
        return f"FAIL {label} {type(err).__name__}: {err}"
    rows = len(out.sections)
    if rows < spec.probe.expect_min_rows:
        return f"FAIL {label} {rows} row(s) (expected >= {spec.probe.expect_min_rows})"
    return f"PASS {label} {rows} row(s)"


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/schedule/replay/test_cli.py -q`
Expected: all PASS.

- [ ] **Step 5: Update CLAUDE.md**

In `CLAUDE.md`, under "## Commands", add after the Schedule CLI block:

```bash
# Replay-spec CLI (data-driven adapters; run/probe hit live portals)
uv run python -m src.schedule.replay.cli validate
uv run python -m src.schedule.replay.cli run --cc-id 27 --term "Fall 2026" --course "MATH 400"
uv run python -m src.schedule.replay.cli probe
```

Under "### Schedule Layer", add after the `term.py` bullet:

```markdown
- `errors.py` — `ScheduleLookupError`, `PortalChanged` (portal answered in an unexpected shape), `SpecInvalid`
- `generic_replay.py` — `GenericReplayProvider`: `ScheduleProvider` for `system == "replay"`; replays the college's spec from `data/specs/<cc_id>.json` and is registered last in `CompositeProvider`
- `replay/` — the replay engine: `spec.py` (frozen model + `schema.json` validation + semantic checks), `registry.py` (loads all specs once, fails fast), `inputs.py` (placeholders like `{term}`, `{subject}`, `{number}`), `captures.py` (cookie/regex/json/css/term-lookup), `executor.py` (steps, per-instance cache, bounded pagination, per-host throttle, one retry), `extractor.py` (JSON or HTML rows to `ParsedSection`), `jsonpath.py` (tiny JSONPath subset), `cli.py`
```

Under "**Scrapers**", add:

```markdown
- `data/specs/*.json` — replay specs: Riverside district (78, 148, 149: SharePoint OData), NOCCCD (71, 134: static JSON with a term lookup), Los Rios (27, 142, 145, 126: HTML cards, paginated)
```

Under "## Key Design Decisions", add:

```markdown
**Replay specs are data, not code:** a spec is a schema-validated JSON file of at most five HTTP steps plus an extraction block. No loops, conditionals, JavaScript, or login. Pagination is a declared, bounded primitive. Invalid specs fail at load, and `tests/schedule/replay/test_specs_registry.py` requires every `"system": "replay"` catalog entry to have a spec with the same `cc_id` and name.

**Course-code drift is a Phase 3 problem:** Riverside district specs send ASSIST codes as-is (`MAT-1B`), which no longer match live codes (`MATH-C2220`); those courses show "Not offered" until the alias table lands.
```

- [ ] **Step 6: Update README.md**

In `README.md`, change the "Current status" line to:

```markdown
**Current status (v0.2):** tuned for UCLA CS; ASSIST ingest fairly complete; schedule coverage about 50 community colleges across Colleague, Banner 9, VSB, WVM, and nine replay-spec colleges.
```

Add these rows to the "Supported colleges and adapters" table:

```markdown
| Riverside City College        | 78      | `replay` — RCCD Class Finder OData (`data/specs/78.json`)     | works (codes drift; see note) |
| Norco College                 | 148     | `replay` — RCCD Class Finder OData (`data/specs/148.json`)    | works (codes drift; see note) |
| Moreno Valley College         | 149     | `replay` — RCCD Class Finder OData (`data/specs/149.json`)    | works (codes drift; see note) |
| Cypress College               | 71      | `replay` — NOCCCD static JSON (`data/specs/71.json`)          | works       |
| Fullerton College             | 134     | `replay` — NOCCCD static JSON (`data/specs/134.json`)         | works       |
| American River College        | 27      | `replay` — Los Rios class search HTML (`data/specs/27.json`)  | works       |
| Cosumnes River College        | 142     | `replay` — Los Rios class search HTML (`data/specs/142.json`) | works       |
| Folsom Lake College           | 145     | `replay` — Los Rios class search HTML (`data/specs/145.json`) | works       |
| Sacramento City College       | 126     | `replay` — Los Rios class search HTML (`data/specs/126.json`) | works       |
```

After the paragraph that starts "`colleague_selfservice` uses Ellucian's...", add:

```markdown
`replay` is a data-driven adapter: each college has a JSON spec at `src/schedule/data/specs/<cc_id>.json` describing up to five HTTP steps (with placeholders such as `{term}`, `{subject}`, `{number}`, values captured from earlier responses, optional caching and bounded pagination) and an extraction block that maps JSON paths or CSS selectors to sections and meetings. Specs are validated against `src/schedule/replay/schema.json` at load. Check them with:

```bash
uv run python -m src.schedule.replay.cli validate
```

Run one college's spec live, or probe every spec with its recorded probe course:

```bash
uv run python -m src.schedule.replay.cli run --cc-id 27 --term "Fall 2026" --course "MATH 400"
```

```bash
uv run python -m src.schedule.replay.cli probe
```

Note on the Riverside district: ASSIST still lists pre-common-course-numbering codes (`MAT 1B`) while the live schedule uses `MATH-C2220`, so those rows show "Not offered" until course aliases land in Phase 3.
```

- [ ] **Step 7: Run the full suite and commit**

Run: `uv run pytest -q` — expected: all pass.

```bash
git add src/schedule/replay/cli.py tests/schedule/replay/test_cli.py README.md CLAUDE.md
git commit -m "feat(schedule): add replay-spec CLI (validate, run, probe) and document the replay adapter"
```

- [ ] **Step 8: Manual live check — validate and probe every spec**

Run:

```bash
uv run python -m src.schedule.replay.cli validate
```

Expected: `9 spec(s) valid in .../src/schedule/data/specs`.

Run:

```bash
uv run python -m src.schedule.replay.cli probe
```

Expected: nine `PASS` lines. Known-good counts on 2026-09-23: Riverside `MATH-C2220` 4 rows; Cypress `MATH 150AC` at least 1; Fullerton `MATH 151` at least 6; American River `MATH 400` 15. If Riverside returns `HTTPError` 403, the app proxy rejected the identifying User-Agent: retry with `USER_AGENT` set to the plain browser string used by `banner9_ssb.py` and record which one worked in the spec `notes`. If Folsom Lake or Sacramento City return 0 rows for `MATH 400`, look up a course those colleges actually offer in Fall 2026 on the Los Rios search page and change that spec's `probe.course_code` (and the catalog `probe_course`) to it; do not change the filters.

- [ ] **Step 9: Manual live check — one full search through the service**

Run:

```bash
uv run python -m src.schedule.cli query --target-school "University of California, Los Angeles" --target-major "Computer Science" --term "Fall 2026" --cc-name "American River"
```

Expected: JSON rows for `MATH 400`, `MATH 401`, `MATH 402`, `MATH 410`, `MATH 420`, `PHYS 410`, `ENGWR 300`, `ENGWR 301`, `CISP 360`, `CISP 400`, `CISP 310`, `CISP 440`, `MATH 61`, `SCI 33`; the MATH rows have `offered: true` with meetings carrying `days` and `start_local`; rows with `lookup_error` must be absent. Repeat with `--cc-name "Cypress"` (expect `MATH 150AC`, `MATH 250AC` offered) and `--cc-name "Riverside City"` (expect every row `offered: false` with `lookup_error: null` — the known numbering limitation, not an error).

- [ ] **Step 10: Manual live check — the web UI**

Start the server (`uv run uvicorn src.web.app:app --reload`), open `http://127.0.0.1:8000`, search UCLA / Computer Science / Fall 2026 with the Pacific timezone. Expected: American River, Cosumnes River, Folsom Lake, Sacramento City, Cypress, and Fullerton appear with "Offered" badges and meeting times; the "fits my hours" and modality filters work on their sections; the Riverside district shows "Not offered" (not "Couldn't check"). Record any college that shows "Couldn't check" with its reason in the PR description; do not paper over it in the spec.

- [ ] **Step 11: Record live results and commit any spec corrections**

If step 8 or 9 required a spec change (probe course, User-Agent note), commit it:

```bash
git add src/schedule/data/specs src/schedule/data/colleges.json src/schedule/replay/executor.py
git commit -m "fix(catalog): adjust replay probes after live verification"
```

---

## Self-review notes

**Spec coverage (design doc section 7 and phase 2 of section 14):**
- 7.1 spec format: one JSON file per college under `src/schedule/data/specs/<cc_id>.json` (Task 2 registry, Tasks 8–10 files); `GET`/`POST` with `query`/`form`/`json`/`headers` and placeholders anywhere (Task 5); `captures` for cookie, regex, CSS selector, JSON path (Task 4) plus a `lookup` capture for term tables, which the design did not list but three of the nine colleges need; `extract.kind` `json` and `html` (Task 6). `extract.kind: regex` from the design is not implemented: no surveyed portal needs it and a field-level `regex` on any value rule covers the same ground. The design says unknown fields are ignored; this plan rejects them at load instead (schema `additionalProperties: false`) so typos surface immediately.
- 7.2 executor: per-college session (one executor per provider instance, Task 7), fixed timeouts, one retry on connection error, per-host rate limit (Task 5). Extractor and `GenericReplayProvider` registered last (Tasks 6, 7). Shared modality/time normalization lives in `normalize.py` (Task 1 additions only; no rule duplicated).
- Section 12 errors: `ScheduleLookupError` and `PortalChanged` (Task 1), spec validation at load naming the field (Task 2), `PortalChanged` mapped to a student-facing reason (Task 7). `PortalUnreachable` and `ExtractionEmpty` are not separate classes: `requests.ConnectionError` already drives the "unreachable" path in `service.py`, and an empty row set is a legitimate "not offered", while a missing rows container is `PortalChanged`.
- Section 13 tests: executor and extractor unit tests over spec primitives with synthetic responses (Tasks 5, 6); each district's specs against recorded fixtures (Tasks 8–10); suite stays offline; live checks are explicit (Task 11).
- Section 14 phase 2: Riverside, Norco, Moreno Valley plus two more L0 custom portals (NOCCCD, Los Rios) — nine colleges.

**Deliberate scope limits:** no web UI changes (Phase 1 already renders meetings, modality, fit, stale, and lookup errors); no course aliasing (Phase 3); NOCCCD section titles are empty because they live in a second file this format does not join (the UI shows the ASSIST title anyway); Los Rios cards with several `li.section` entries (linked lecture + lab) report only the first section id.

**Type consistency checked:** `ValueRule`, `Capture`, `Paginate`, `Step`, `FilterRule`, `MeetingRule`, `Extract`, `ReplaySpec` field names are identical in Task 2 (definitions), Task 5/6 (use), and Tasks 8–10 (JSON keys map one-to-one: `days.flags`, `time_text`/`time_pattern`, `join`, `any_of`, `from_seats`, `total_capture`). `evaluate_capture` keyword names match between Task 4 and Task 5. `FakeSession.request` signature matches `ReplayExecutor._send_once`'s call. `GenericReplayProvider(executor=, specs=)` matches Tasks 7–11.
