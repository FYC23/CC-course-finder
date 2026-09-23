# Phase 1: Section Model, Banner 9, and Colleague Config — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every section real meeting days, times, modality, and seat counts; turn the two largest portal families (Banner 9 and Colleague Self-Service) into correctly named, per-district-configurable adapters; and expand the catalog from 10 colleges to about 40 with the stale entries fixed.

**Architecture:** The section model gains a frozen `Meeting` type and shared normalization helpers. The two misnamed adapters are renamed to their real families and taught to parse meetings from the JSON both portals already return. The catalog schema gains `params` and `status` so district-specific term codes, location codes, and unsupported portals are data rather than code. The web layer exposes meetings and computes a per-section timezone fit when the client sends its UTC offset. No model, no browser, and no new network behavior in the query path.

**Tech Stack:** Python 3.12, uv, `requests`, FastAPI, pytest with `unittest.mock`, vanilla JS in `src/web/templates/index.html`.

**Spec:** `docs/superpowers/specs/2026-09-22-agentic-coverage-design.md` (sections 5, 6, 11, 12, 13, and phase 1 of section 14). Survey evidence: `docs/superpowers/specs/portal-survey-2026-09-22.csv`.

## Global Constraints

- Python `>=3.12`, run everything with `uv run ...`; tests with `uv run pytest`.
- All dataclasses are `frozen=True`. Never mutate an existing object; build a new one.
- Files stay under 800 lines; prefer 200–400. Functions under 50 lines. Split rather than grow.
- No LLM, no browser, no login, no CAPTCHA handling anywhere in this phase.
- No vendor SDKs of any kind are added in this phase.
- Adapters never guess modality. Unknown stays `"unknown"`.
- Existing behavior for VSB, WVM static, Marin, and SMCCD adapters must not change except for the catalog `status` field.
- Commit after every task with a conventional-commit message (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`). Do not add attribution trailers (disabled in this user's global settings).
- Keep 80% coverage. Run the full suite (`uv run pytest`) before every commit; all 181 existing tests plus new ones must pass.

---

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `src/schedule/models.py` | `Meeting`, `ParsedSection`, `CourseAvailability`, `CollegeScheduleSource` with `params` and `status` | modify |
| `src/schedule/normalize.py` | day, time, date, modality, status normalization shared by adapters | create |
| `src/schedule/fit.py` | timezone-fit classification of a section for a student UTC offset | create |
| `src/schedule/catalog.py` | schema v2 validation, system aliases, `params`, `status` | modify |
| `src/schedule/service.py` | skip `unsupported` colleges instead of raising | modify |
| `src/schedule/banner9_ssb.py` | renamed from `banner_ssb_classic.py`; parses meetings, faculty, seats, campus filter | rename + modify |
| `src/schedule/colleague_selfservice.py` | renamed from `banner_ellucian.py`; anti-forgery token, term resolution, empty locations | rename + modify |
| `src/schedule/colleague_sections.py` | section and meeting parsing for Colleague JSON (split out to keep the adapter under 800 lines) | create |
| `src/schedule/composite.py` | register renamed providers | modify |
| `src/schedule/data/colleges.json` | schema v2 entries: fixes plus ~30 new colleges | modify |
| `scripts/discover_colleague.py` | prints a Colleague portal's term codes and location codes | create |
| `src/web/serialize.py` | section → dict with optional `fit` | create |
| `src/web/routers/search.py` | `utc_offset` query param, uses serializer | modify |
| `src/web/templates/index.html` | days/time/seats columns, modality filter, hours-fit filter | modify |
| `src/web/static/style.css` | fit badge colors | modify |
| `tests/schedule/test_normalize.py`, `test_fit.py`, `test_banner9_ssb.py`, `test_colleague_sections.py`, `test_colleague_selfservice.py` | new tests | create |
| `tests/schedule/test_catalog.py`, `test_service.py`, `test_pilot_provider.py`, `test_banner_ellucian.py`, `test_banner_ssb_classic.py` | updated for renames and schema v2 | modify / rename |
| `tests/web/test_routes.py`, `tests/web/test_serialize.py` | `utc_offset` and serializer tests | modify / create |
| `CLAUDE.md`, `README.md` | adapter names and catalog schema | modify |

---

### Task 1: Meeting model and normalization helpers

**Files:**
- Modify: `src/schedule/models.py`
- Create: `src/schedule/normalize.py`
- Test: `tests/schedule/test_normalize.py`

**Interfaces:**
- Produces: `Meeting(days, start_local, end_local, timezone, location, is_online, start_date, end_date)`; `ParsedSection` gains `meetings: tuple[Meeting, ...] = ()`, `seats_total: int | None = None`, `seats_used: int | None = None`, `course_code_as_listed: str = ""`; constants `DAY_CODES`, `MODALITIES`, `STATUSES`.
- Produces: `normalize.parse_hhmm(raw) -> time | None`, `normalize.parse_date(raw) -> date | None`, `normalize.days_from_flags(flags) -> tuple[str, ...]`, `normalize.days_from_indices(indices) -> tuple[str, ...]`, `normalize.normalize_modality(*, raw_tokens, meetings) -> str`, `normalize.normalize_status(raw) -> str`, `normalize.int_or_none(value) -> int | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/schedule/test_normalize.py`:

```python
from __future__ import annotations

from datetime import date, time

import pytest

from src.schedule.models import Meeting, ParsedSection
from src.schedule.normalize import (
    days_from_flags,
    days_from_indices,
    int_or_none,
    normalize_modality,
    normalize_status,
    parse_date,
    parse_hhmm,
)


# --- time parsing -----------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0730", time(7, 30)),
        ("1345", time(13, 45)),
        ("10:45:00", time(10, 45)),
        ("10:45", time(10, 45)),
        ("10:45 AM", time(10, 45)),
        ("02:20PM", time(14, 20)),
        ("12:05 PM", time(12, 5)),
        ("12:10AM", time(0, 10)),
        ("", None),
        (None, None),
        ("TBA", None),
    ],
)
def test_parse_hhmm(raw, expected):
    assert parse_hhmm(raw) == expected


# --- date parsing -----------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("08/24/2026", date(2026, 8, 24)),
        ("2026-08-24T00:00:00-07:00", date(2026, 8, 24)),
        ("2026-08-24", date(2026, 8, 24)),
        ("08/24/26", date(2026, 8, 24)),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


# --- days -------------------------------------------------------------------

def test_days_from_flags_orders_monday_first():
    flags = {"monday": True, "wednesday": True, "sunday": True, "tuesday": False}
    assert days_from_flags(flags) == ("M", "W", "U")


def test_days_from_flags_ignores_unknown_keys():
    assert days_from_flags({"funday": True, "friday": True}) == ("F",)


def test_days_from_indices_colleague_convention():
    # Colleague: 0=Sunday ... 6=Saturday
    assert days_from_indices([1, 3]) == ("M", "W")
    assert days_from_indices([0, 6]) == ("S", "U")
    assert days_from_indices([]) == ()
    assert days_from_indices([9, -1]) == ()


# --- modality ---------------------------------------------------------------

def _meeting(**kw) -> Meeting:
    return Meeting(**kw)


def test_modality_hybrid_token_wins():
    assert normalize_modality(raw_tokens=["Hybrid"], meetings=()) == "hybrid"


def test_modality_online_with_no_times_is_async():
    m = _meeting(is_online=True)
    assert normalize_modality(raw_tokens=["Online"], meetings=(m,)) == "async_online"


def test_modality_online_with_times_is_sync():
    m = _meeting(is_online=True, days=("M",), start_local=time(9), end_local=time(10))
    assert normalize_modality(raw_tokens=["Online"], meetings=(m,)) == "sync_online"


def test_modality_online_token_alone_is_async():
    assert normalize_modality(raw_tokens=["OL"], meetings=()) == "async_online"


def test_modality_lecture_with_room_is_in_person():
    m = _meeting(days=("T",), start_local=time(9), end_local=time(10), location="MS3 217")
    assert normalize_modality(raw_tokens=["Lecture"], meetings=(m,)) == "in_person"


def test_modality_mixed_meetings_is_hybrid():
    online = _meeting(is_online=True)
    room = _meeting(days=("T",), start_local=time(9), end_local=time(10), location="QD 116")
    assert normalize_modality(raw_tokens=[], meetings=(online, room)) == "hybrid"


def test_modality_no_evidence_is_unknown():
    assert normalize_modality(raw_tokens=[], meetings=()) == "unknown"
    assert normalize_modality(raw_tokens=["02"], meetings=()) == "unknown"


# --- status -----------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Open", "open"),
        ("open seats", "open"),
        ("Closed", "closed"),
        ("Full", "closed"),
        ("Cancelled", "closed"),
        ("Waitlisted", "waitlist"),
        ("Waitlist", "waitlist"),
        ("", "unknown"),
        (None, "unknown"),
        ("Something else", "unknown"),
    ],
)
def test_normalize_status(raw, expected):
    assert normalize_status(raw) == expected


# --- ints -------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [(3, 3), (3.0, 3), ("42", 42), ("", None), (None, None), ("x", None), (-4, -4)])
def test_int_or_none(value, expected):
    assert int_or_none(value) == expected


# --- model defaults ---------------------------------------------------------

def test_parsed_section_defaults_are_backward_compatible():
    s = ParsedSection(section_id="1", status="open", modality="unknown", title="T", instructor="")
    assert s.meetings == ()
    assert s.seats_total is None
    assert s.seats_used is None
    assert s.course_code_as_listed == ""


def test_meeting_is_frozen():
    m = Meeting(days=("M",))
    with pytest.raises(Exception):
        m.days = ("T",)  # type: ignore[misc]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/schedule/test_normalize.py -q`
Expected: FAIL with `ImportError: cannot import name 'Meeting'` (or `ModuleNotFoundError: src.schedule.normalize`).

- [ ] **Step 3: Extend the models**

Replace the contents of `src/schedule/models.py` with:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, time
from types import MappingProxyType

DAY_CODES: tuple[str, ...] = ("M", "T", "W", "R", "F", "S", "U")
MODALITIES: tuple[str, ...] = ("async_online", "sync_online", "hybrid", "in_person", "unknown")
STATUSES: tuple[str, ...] = ("open", "closed", "waitlist", "unknown")
CATALOG_STATUSES: tuple[str, ...] = ("active", "stale", "unsupported")
DEFAULT_CAMPUS_TZ = "America/Los_Angeles"


def _empty_params() -> Mapping[str, str]:
    return MappingProxyType({})


@dataclass(frozen=True)
class CollegeScheduleSource:
    cc_id: int
    cc_name: str
    system: str
    base_url: str
    locations: tuple[str, ...]
    params: Mapping[str, str] = field(default_factory=_empty_params, compare=False, hash=False)
    status: str = "active"


@dataclass(frozen=True)
class Meeting:
    """One recurring meeting block of a section. Times are campus-local."""

    days: tuple[str, ...] = ()
    start_local: time | None = None
    end_local: time | None = None
    timezone: str = DEFAULT_CAMPUS_TZ
    location: str = ""
    is_online: bool = False
    start_date: date | None = None
    end_date: date | None = None

    @property
    def is_timed(self) -> bool:
        return self.start_local is not None and self.end_local is not None


@dataclass(frozen=True)
class ParsedSection:
    section_id: str
    status: str
    modality: str
    title: str
    instructor: str
    meetings: tuple[Meeting, ...] = ()
    seats_total: int | None = None
    seats_used: int | None = None
    course_code_as_listed: str = ""


@dataclass(frozen=True)
class CourseAvailability:
    cc_id: int
    cc_name: str
    term: str
    course_code: str
    offered: bool
    sections: list[ParsedSection]
    source_url: str
    raw_summary: str = ""
```

- [ ] **Step 4: Write the normalization module**

Create `src/schedule/normalize.py`:

```python
"""Normalization helpers shared by every schedule adapter.

Adapters translate portal-specific fields into the enums in models.py through
these functions so that the rules live in one place and never guess.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time

from .models import Meeting

_DAY_KEY_TO_CODE: Mapping[str, str] = {
    "monday": "M",
    "tuesday": "T",
    "wednesday": "W",
    "thursday": "R",
    "friday": "F",
    "saturday": "S",
    "sunday": "U",
}
_DAY_ORDER: tuple[str, ...] = ("M", "T", "W", "R", "F", "S", "U")
# Colleague's Days array uses 0=Sunday ... 6=Saturday.
_INDEX_TO_CODE: Mapping[int, str] = {0: "U", 1: "M", 2: "T", 3: "W", 4: "R", 5: "F", 6: "S"}

_HHMM_RE = re.compile(r"^(\d{1,2}):?(\d{2})(?::\d{2})?\s*([AaPp][Mm])?$")

_STATUS_MAP: Mapping[str, str] = {
    "open": "open",
    "open seats": "open",
    "closed": "closed",
    "full": "closed",
    "cancelled": "closed",
    "canceled": "closed",
    "waitlist": "waitlist",
    "waitlisted": "waitlist",
}

# Matched as whole words after lowercasing and splitting on non-letters, so "ol" never
# matches inside "College" and "lab" never matches inside "Collaborative".
_HYBRID_WORDS = frozenset({"hybrid", "hyb"})
_ONLINE_WORDS = frozenset(
    {"online", "ol", "web", "distance", "asynchronous", "synchronous", "remote", "internet", "de"}
)
_SYNC_WORDS = frozenset({"synchronous", "sync", "regmeet"})
_IN_PERSON_WORDS = frozenset(
    {"lecture", "lec", "lab", "laboratory", "person", "campus", "classroom", "discussion"}
)
_WORD_RE = re.compile(r"[a-z]+")


def parse_hhmm(raw: object) -> time | None:
    """Parse '0730', '10:45', '10:45:00', '10:45 AM', '02:20PM'. Returns None if unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    match = _HHMM_RE.match(text)
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = (match.group(3) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def parse_date(raw: object) -> date | None:
    """Parse '08/24/2026', '08/24/26', '2026-08-24', or an ISO datetime. None if unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def days_from_flags(flags: Mapping[str, object]) -> tuple[str, ...]:
    """Banner-style {'monday': True, ...} to ('M', ...), always in weekday order."""
    present = {_DAY_KEY_TO_CODE[k.lower()] for k, v in flags.items() if k.lower() in _DAY_KEY_TO_CODE and v}
    return tuple(code for code in _DAY_ORDER if code in present)


def days_from_indices(indices: Iterable[object]) -> tuple[str, ...]:
    """Colleague-style [1, 3] (0=Sunday) to ('M', 'W'), always in weekday order."""
    present = {_INDEX_TO_CODE[i] for i in indices if isinstance(i, int) and i in _INDEX_TO_CODE}
    return tuple(code for code in _DAY_ORDER if code in present)


def normalize_status(raw: object) -> str:
    if not isinstance(raw, str):
        return "unknown"
    return _STATUS_MAP.get(raw.strip().lower(), "unknown")


def int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def normalize_modality(*, raw_tokens: Iterable[str], meetings: Sequence[Meeting]) -> str:
    """Map portal wording plus meeting evidence to the modality enum. Never guesses."""
    text = " ".join(t.lower() for t in raw_tokens if isinstance(t, str))
    words = frozenset(_WORD_RE.findall(text.replace("reg-meet", "regmeet").replace("reg meet", "regmeet")))
    from_text = _modality_from_words(words, meetings)
    if from_text is not None:
        return from_text
    return _modality_from_meetings(meetings)


def _modality_from_words(words: frozenset[str], meetings: Sequence[Meeting]) -> str | None:
    if not words:
        return None
    if words & _HYBRID_WORDS:
        return "hybrid"
    if words & _ONLINE_WORDS:
        if words & _SYNC_WORDS or any(m.is_timed for m in meetings):
            return "sync_online"
        return "async_online"
    if words & _IN_PERSON_WORDS:
        if meetings and all(m.is_online for m in meetings):
            return "sync_online" if any(m.is_timed for m in meetings) else "async_online"
        return "in_person"
    return None


def _modality_from_meetings(meetings: Sequence[Meeting]) -> str:
    if not meetings:
        return "unknown"
    online = [m for m in meetings if m.is_online]
    in_person = [m for m in meetings if not m.is_online]
    if online and in_person:
        return "hybrid"
    if online:
        return "sync_online" if any(m.is_timed for m in online) else "async_online"
    return "in_person"
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/schedule/test_normalize.py -q`
Expected: all PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. (`ParsedSection` and `CollegeScheduleSource` only gained defaulted fields, so every existing constructor call still works.)

- [ ] **Step 7: Commit**

```bash
git add src/schedule/models.py src/schedule/normalize.py tests/schedule/test_normalize.py
git commit -m "feat(schedule): add Meeting model, seats, and shared normalization helpers"
```

---

### Task 2: Catalog schema v2 and system renames

**Files:**
- Modify: `src/schedule/catalog.py`
- Modify: `src/schedule/service.py:36-46`
- Modify: `src/schedule/data/colleges.json` (system values only in this task)
- Modify: `tests/schedule/test_catalog.py`
- Modify: `tests/schedule/test_service.py:21,117`

**Interfaces:**
- Consumes: `CollegeScheduleSource(params, status)` from Task 1.
- Produces: `catalog.KNOWN_SYSTEMS` = `{"colleague_selfservice", "banner9_ssb", "wvm_static", "vsb_4cd", "marin_colleague", "smcccd_colleague"}`; `catalog.SYSTEM_ALIASES` = `{"banner": "colleague_selfservice", "banner_ssb_classic": "banner9_ssb"}`; `catalog.list_college_sources() -> list[CollegeScheduleSource]`. Entries may carry `params` (dict of str→str), `status` (`active|stale|unsupported`), `provenance` (dict, stored but unused this phase), `note` (str).
- Produces: `ScheduleService.query` skips sources whose `status == "unsupported"`.

- [ ] **Step 1: Write the failing tests**

In `tests/schedule/test_catalog.py`, change `_VALID_ENTRY` and the smoke-test system list, and add new tests. Replace the `_VALID_ENTRY` block with:

```python
_VALID_ENTRY = {
    "cc_id": 999,
    "cc_name": "Test College",
    "system": "colleague_selfservice",
    "base_url": "https://example.edu",
    "locations": ["TC"],
}
```

Replace the assertion list inside `test_get_college_source_all_entries` with:

```python
    assert src.system in (
        "colleague_selfservice",
        "banner9_ssb",
        "wvm_static",
        "vsb_4cd",
        "marin_colleague",
        "smcccd_colleague",
    )
```

Delete `test_validate_entry_empty_locations` and `test_load_empty_locations` (empty locations become legal), and delete the line `assert len(src.locations) > 0` from `test_get_college_source_all_entries` for the same reason. Append these tests:

```python
# ---------------------------------------------------------------------------
# Schema v2: aliases, params, status
# ---------------------------------------------------------------------------

def test_legacy_system_names_are_aliased(tmp_path: Path):
    data = [
        {**_VALID_ENTRY, "cc_id": 1, "cc_name": "Old Banner", "system": "banner"},
        {**_VALID_ENTRY, "cc_id": 2, "cc_name": "Old Classic", "system": "banner_ssb_classic"},
    ]
    _reload(_write_json(tmp_path, data))
    assert get_college_source(1).system == "colleague_selfservice"
    assert get_college_source(2).system == "banner9_ssb"


def test_empty_locations_are_allowed(tmp_path: Path):
    _reload(_write_json(tmp_path, [{**_VALID_ENTRY, "locations": []}]))
    assert get_college_source(999).locations == ()


def test_params_are_loaded_as_read_only_mapping(tmp_path: Path):
    entry = {**_VALID_ENTRY, "params": {"term_format": "{yyyy}{SEASON2}", "campus_codes": "BB,BC"}}
    _reload(_write_json(tmp_path, [entry]))
    src = get_college_source(999)
    assert src.params["term_format"] == "{yyyy}{SEASON2}"
    with pytest.raises(TypeError):
        src.params["x"] = "y"  # type: ignore[index]


def test_params_must_be_string_map():
    with pytest.raises(ValueError, match="params"):
        _validate_entry({**_VALID_ENTRY, "params": {"n": 3}})
    with pytest.raises(ValueError, match="params"):
        _validate_entry({**_VALID_ENTRY, "params": ["a"]})


def test_status_defaults_to_active(tmp_path: Path):
    _reload(_write_json(tmp_path, [_VALID_ENTRY]))
    assert get_college_source(999).status == "active"


def test_status_must_be_known():
    with pytest.raises(ValueError, match="status"):
        _validate_entry({**_VALID_ENTRY, "status": "broken"})


def test_status_unsupported_is_loaded(tmp_path: Path):
    _reload(_write_json(tmp_path, [{**_VALID_ENTRY, "status": "unsupported", "note": "SSO"}]))
    assert get_college_source(999).status == "unsupported"


def test_list_college_sources_returns_all(tmp_path: Path):
    from src.schedule.catalog import list_college_sources
    data = [{**_VALID_ENTRY, "cc_id": 1, "cc_name": "A"}, {**_VALID_ENTRY, "cc_id": 2, "cc_name": "B"}]
    _reload(_write_json(tmp_path, data))
    assert [s.cc_id for s in list_college_sources()] == [1, 2]
```

In `tests/schedule/test_service.py` change line 21 to:

```python
        return source.system in ("colleague_selfservice", "wvm_static")
```

and line 117 to:

```python
    assert source.system == "colleague_selfservice"
```

Append to `tests/schedule/test_service.py`:

```python
def test_query_skips_unsupported_colleges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import json
    from src.schedule import catalog

    db_path = tmp_path / "assist.sqlite3"
    _seed_assist_rows(db_path)
    entries = [
        {
            "cc_id": 2,
            "cc_name": "Evergreen Valley College",
            "system": "colleague_selfservice",
            "base_url": "https://example.edu",
            "locations": ["EVC"],
            "status": "unsupported",
            "note": "test",
        }
    ]
    catalog_file = tmp_path / "colleges.json"
    catalog_file.write_text(json.dumps(entries))
    catalog._reload(catalog_file)
    try:
        provider = _FakeProvider()
        service = ScheduleService(db_path=db_path, provider=provider)
        results = service.query(
            target_school="University of California, Los Angeles",
            target_major="Computer Science",
            term_label="Summer 2026",
        )
        assert results == []
        assert provider.calls == []
    finally:
        catalog._reload()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/schedule/test_catalog.py tests/schedule/test_service.py -q`
Expected: FAIL. Alias tests fail with `Unknown system`, params test fails with `KeyError`/`AttributeError`, status tests fail, `list_college_sources` import fails.

- [ ] **Step 3: Rewrite the catalog loader**

Replace `src/schedule/catalog.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

from .models import CATALOG_STATUSES, CollegeScheduleSource

_DATA_FILE = Path(__file__).parent / "data" / "colleges.json"

KNOWN_SYSTEMS: frozenset[str] = frozenset(
    {
        "colleague_selfservice",
        "banner9_ssb",
        "wvm_static",
        "vsb_4cd",
        "marin_colleague",
        "smcccd_colleague",
    }
)
# Legacy names still accepted on disk and mapped to their real family.
SYSTEM_ALIASES: dict[str, str] = {
    "banner": "colleague_selfservice",
    "banner_ssb_classic": "banner9_ssb",
}
_REQUIRED_KEYS = ("cc_id", "cc_name", "system", "base_url", "locations")


def _canonical_system(name: str) -> str:
    return SYSTEM_ALIASES.get(name, name)


def _validate_entry(e: dict) -> None:
    for key in _REQUIRED_KEYS:
        if key not in e:
            raise ValueError(f"colleges.json entry missing key {key!r}: {e}")
    if _canonical_system(e["system"]) not in KNOWN_SYSTEMS:
        raise ValueError(f"Unknown system {e['system']!r} in entry cc_id={e['cc_id']}")
    if not isinstance(e["locations"], list):
        raise ValueError(f"locations must be a list for cc_id={e['cc_id']}")
    if "source_url" in e and not isinstance(e["source_url"], str):
        raise ValueError(f"source_url must be string for cc_id={e['cc_id']}")
    _validate_params(e)
    _validate_status(e)


def _validate_params(e: dict) -> None:
    params = e.get("params", {})
    if not isinstance(params, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in params.items()
    ):
        raise ValueError(f"params must be a string-to-string object for cc_id={e['cc_id']}")


def _validate_status(e: dict) -> None:
    status = e.get("status", "active")
    if status not in CATALOG_STATUSES:
        raise ValueError(
            f"status must be one of {CATALOG_STATUSES} for cc_id={e['cc_id']}, got {status!r}"
        )


def _to_source(e: dict) -> CollegeScheduleSource:
    return CollegeScheduleSource(
        cc_id=e["cc_id"],
        cc_name=e["cc_name"],
        system=_canonical_system(e["system"]),
        base_url=e["base_url"],
        locations=tuple(e["locations"]),
        params=MappingProxyType(dict(e.get("params", {}))),
        status=e.get("status", "active"),
    )


def _load(path: Path | None = None) -> dict[int, CollegeScheduleSource]:
    target = path or _DATA_FILE
    try:
        data = json.loads(target.read_text())
    except FileNotFoundError as exc:
        raise RuntimeError(f"colleges.json missing: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"colleges.json corrupt: {exc}") from exc
    for e in data:
        _validate_entry(e)
    return {e["cc_id"]: _to_source(e) for e in data}


_SOURCES_BY_CC_ID: dict[int, CollegeScheduleSource] = _load()


def _reload(path: Path | None = None) -> None:
    """Reload catalog from *path* (or default data file). Intended for tests."""
    global _SOURCES_BY_CC_ID
    _SOURCES_BY_CC_ID = _load(path)


def get_college_source(cc_id: int) -> CollegeScheduleSource:
    source = _SOURCES_BY_CC_ID.get(cc_id)
    if source is None:
        raise KeyError(f"No schedule source configured for cc_id={cc_id}")
    return source


def list_college_sources() -> list[CollegeScheduleSource]:
    return list(_SOURCES_BY_CC_ID.values())


def find_college_source_by_name(name: str) -> CollegeScheduleSource:
    """Case-insensitive substring match. Raises KeyError if 0 or >1 matches."""
    needle = name.strip().lower()
    matches = [s for s in _SOURCES_BY_CC_ID.values() if needle in s.cc_name.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) == 0:
        raise KeyError(f"No schedule source matches name={name!r}")
    names = ", ".join(f"{s.cc_name!r} (cc_id={s.cc_id})" for s in matches)
    raise KeyError(f"Ambiguous name {name!r} matches: {names}")
```

- [ ] **Step 4: Make the service skip unsupported colleges**

In `src/schedule/service.py`, inside the `for row_cc_id, course_code in course_keys:` loop, directly after the `except KeyError: continue` block, add:

```python
            if source.status == "unsupported":
                continue
```

- [ ] **Step 5: Rename systems in the data file**

In `src/schedule/data/colleges.json` change every `"system": "banner"` to `"system": "colleague_selfservice"` and every `"system": "banner_ssb_classic"` to `"system": "banner9_ssb"`. (Task 6 rewrites the whole file; this keeps the suite green meanwhile. Note the LACC entry's system is wrong but is fixed in Task 6.)

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/schedule/test_catalog.py tests/schedule/test_service.py -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: FAIL only in `tests/schedule/test_banner_ellucian.py` and `tests/schedule/test_pilot_provider.py` (`supports_source` still checks `"banner"`) and `tests/schedule/test_banner_ssb_classic.py` (checks `"banner_ssb_classic"`). Those adapters are fixed in Tasks 3 and 4. To keep this commit green, make the two adapters accept the new names now with one-line edits:

In `src/schedule/banner_ellucian.py` line 55 change `return source.system == "banner" and bool(source.locations)` to:

```python
        return source.system == "colleague_selfservice"
```

In `src/schedule/banner_ssb_classic.py` line 50 change `return source.system == "banner_ssb_classic"` to:

```python
        return source.system == "banner9_ssb"
```

Then update the fixtures in the three test files: replace `system="banner"` with `system="colleague_selfservice"` in `tests/schedule/test_banner_ellucian.py` and `tests/schedule/test_pilot_provider.py`, and `system="banner_ssb_classic"` with `system="banner9_ssb"` in `tests/schedule/test_banner_ssb_classic.py`. Run:

```bash
sed -i '' 's/system="banner"/system="colleague_selfservice"/g; s/system="banner_ssb_classic"/system="banner9_ssb"/g' tests/schedule/test_banner_ellucian.py tests/schedule/test_pilot_provider.py tests/schedule/test_banner_ssb_classic.py
```

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/schedule/catalog.py src/schedule/service.py src/schedule/data/colleges.json src/schedule/banner_ellucian.py src/schedule/banner_ssb_classic.py tests/schedule/
git commit -m "feat(schedule): catalog schema v2 with params, status, and family-name aliases"
```

---

### Task 3: Banner 9 adapter with meetings, faculty, seats, and campus filter

**Files:**
- Rename: `src/schedule/banner_ssb_classic.py` → `src/schedule/banner9_ssb.py`
- Rename: `tests/schedule/test_banner_ssb_classic.py` → `tests/schedule/test_banner9_ssb.py`
- Modify: `src/schedule/composite.py`

**Interfaces:**
- Consumes: `Meeting`, `ParsedSection`, `normalize.*` from Task 1; `source.params["campus_codes"]` (comma-separated Banner campus codes, optional) from Task 2.
- Produces: `Banner9SsbProvider` (same constructor and methods as the old class), `_resolve_term_code` unchanged, `_parse_row(row: dict) -> ParsedSection`, `_parse_meeting(meeting_time: dict) -> Meeting`, `_row_matches_campus(row, codes) -> bool`.

Reference shape of one `searchResults` row (captured from Mt. SAC, Fall 2026, MATH 180):

```json
{
  "courseReferenceNumber": "21216", "subject": "MATH", "courseNumber": "180",
  "subjectCourse": "MATH180", "courseTitle": "Calculus and Analytic Geometry",
  "openSection": true, "seatsAvailable": -4, "maximumEnrollment": 40, "enrollment": 36,
  "waitCapacity": 10, "waitCount": 4,
  "instructionalMethod": "02", "instructionalMethodDescription": "Lecture and/or Discussion",
  "campusDescription": "Mt. San Antonio College",
  "faculty": [{"displayName": "Nguyen, Bao-Chi T", "primaryIndicator": true}],
  "meetingsFaculty": [{"meetingTime": {
      "beginTime": "0730", "endTime": "0935", "building": "61", "buildingDescription": "Bldg 61",
      "room": "2306", "campus": "MS", "startDate": "08/24/2026", "endDate": "12/13/2026",
      "monday": true, "tuesday": false, "wednesday": true, "thursday": false,
      "friday": false, "saturday": false, "sunday": false, "meetingType": "CLAS"}}]
}
```

- [ ] **Step 1: Rename the files**

```bash
git mv src/schedule/banner_ssb_classic.py src/schedule/banner9_ssb.py
git mv tests/schedule/test_banner_ssb_classic.py tests/schedule/test_banner9_ssb.py
sed -i '' 's/banner_ssb_classic/banner9_ssb/g; s/BannerSsbClassicProvider/Banner9SsbProvider/g' src/schedule/banner9_ssb.py src/schedule/composite.py tests/schedule/test_banner9_ssb.py
```

Run: `uv run pytest tests/schedule/test_banner9_ssb.py -q`
Expected: PASS (pure rename).

- [ ] **Step 2: Write the failing tests**

Append to `tests/schedule/test_banner9_ssb.py`:

```python
# ---------------------------------------------------------------------------
# Row parsing: meetings, faculty, seats, modality, campus filter
# ---------------------------------------------------------------------------

from datetime import date, time  # noqa: E402

from src.schedule.banner9_ssb import _parse_meeting, _parse_row, _row_matches_campus  # noqa: E402
from src.schedule.models import CollegeScheduleSource as _Src  # noqa: E402

_ROW_IN_PERSON = {
    "courseReferenceNumber": "21216", "subject": "MATH", "courseNumber": "180",
    "subjectCourse": "MATH180", "courseTitle": "Calculus and Analytic Geometry",
    "openSection": True, "seatsAvailable": -4, "maximumEnrollment": 40, "enrollment": 36,
    "waitCapacity": 10, "waitCount": 4,
    "instructionalMethod": "02", "instructionalMethodDescription": "Lecture and/or Discussion",
    "campusDescription": "Mt. San Antonio College",
    "faculty": [{"displayName": "Nguyen, Bao-Chi T", "primaryIndicator": True}],
    "meetingsFaculty": [{"meetingTime": {
        "beginTime": "0730", "endTime": "0935", "building": "61", "buildingDescription": "Bldg 61",
        "room": "2306", "campus": "MS", "startDate": "08/24/2026", "endDate": "12/13/2026",
        "monday": True, "tuesday": False, "wednesday": True, "thursday": False,
        "friday": False, "saturday": False, "sunday": False, "meetingType": "CLAS"}}],
}

_ROW_ONLINE = {
    "courseReferenceNumber": "22001", "subject": "MATH", "courseNumber": "180",
    "subjectCourse": "MATH180", "courseTitle": "Calculus and Analytic Geometry",
    "openSection": True, "seatsAvailable": 5, "maximumEnrollment": 40, "enrollment": 35,
    "waitCapacity": 0, "waitCount": 0,
    "instructionalMethod": "OL", "instructionalMethodDescription": "Online",
    "campusDescription": "Mt. San Antonio College",
    "faculty": [],
    "meetingsFaculty": [{"meetingTime": {
        "beginTime": None, "endTime": None, "building": None, "buildingDescription": None,
        "room": None, "campus": "MS", "startDate": "08/24/2026", "endDate": "12/13/2026",
        "monday": False, "tuesday": False, "wednesday": False, "thursday": False,
        "friday": False, "saturday": False, "sunday": False, "meetingType": "CLAS"}}],
}


def test_parse_meeting_in_person():
    m = _parse_meeting(_ROW_IN_PERSON["meetingsFaculty"][0]["meetingTime"])
    assert m.days == ("M", "W")
    assert m.start_local == time(7, 30)
    assert m.end_local == time(9, 35)
    assert m.location == "Bldg 61 2306"
    assert m.is_online is False
    assert m.start_date == date(2026, 8, 24)
    assert m.end_date == date(2026, 12, 13)


def test_parse_meeting_online_has_no_times():
    m = _parse_meeting(_ROW_ONLINE["meetingsFaculty"][0]["meetingTime"])
    assert m.days == ()
    assert m.start_local is None
    assert m.is_online is True


def test_parse_row_in_person():
    s = _parse_row(_ROW_IN_PERSON)
    assert s.section_id == "21216"
    assert s.title == "Calculus and Analytic Geometry"
    assert s.instructor == "Nguyen, Bao-Chi T"
    assert s.modality == "in_person"
    assert s.status == "waitlist"          # open flag but no seats and a waitlist
    assert s.seats_total == 40
    assert s.seats_used == 36
    assert s.course_code_as_listed == "MATH 180"
    assert len(s.meetings) == 1


def test_parse_row_online_async():
    s = _parse_row(_ROW_ONLINE)
    assert s.modality == "async_online"
    assert s.status == "open"
    assert s.instructor == ""


def test_parse_row_closed_when_not_open_and_no_waitlist():
    row = {**_ROW_ONLINE, "openSection": False, "seatsAvailable": 0, "waitCapacity": 0}
    assert _parse_row(row).status == "closed"


def test_row_matches_campus_by_meeting_campus_code():
    assert _row_matches_campus(_ROW_IN_PERSON, ("MS",)) is True
    assert _row_matches_campus(_ROW_IN_PERSON, ("BB", "BC")) is False


def test_row_matches_campus_keeps_rows_without_meetings():
    row = {**_ROW_ONLINE, "meetingsFaculty": []}
    assert _row_matches_campus(row, ("XX",)) is True


def test_search_course_applies_campus_filter_from_params():
    from types import MappingProxyType
    src = _Src(
        cc_id=84, cc_name="Bakersfield College", system="banner9_ssb",
        base_url="https://reg-prod.ec.kccd.edu", locations=(),
        params=MappingProxyType({"campus_codes": "BB,BC"}),
    )
    s = _make_session(search={"totalCount": 2, "data": [_ROW_IN_PERSON, {**_ROW_ONLINE, "meetingsFaculty": [{"meetingTime": {**_ROW_ONLINE["meetingsFaculty"][0]["meetingTime"], "campus": "BB"}}]}]})
    p = Banner9SsbProvider(session=s)
    result = p.search_course(source=src, term=parse_term_label("Summer 2026"), course_code="MATH 180")
    assert [x.section_id for x in result.sections] == ["22001"]


def test_search_course_sections_carry_meetings():
    s = _make_session(search={"totalCount": 1, "data": [_ROW_IN_PERSON]})
    p = Banner9SsbProvider(session=s)
    result = p.search_course(source=_MTSAC, term=parse_term_label("Summer 2026"), course_code="MATH 180")
    assert result.sections[0].meetings[0].days == ("M", "W")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/schedule/test_banner9_ssb.py -q`
Expected: FAIL with `ImportError: cannot import name '_parse_meeting'`.

- [ ] **Step 4: Implement row parsing and the campus filter**

In `src/schedule/banner9_ssb.py`, replace the imports at the top with:

```python
from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests

from .models import CollegeScheduleSource, CourseAvailability, Meeting, ParsedSection
from .normalize import days_from_flags, int_or_none, normalize_modality, parse_date, parse_hhmm
from .term import ParsedTerm
```

Add these module-level functions after `_parse_course_code`:

```python
_DAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_ONLINE_LOCATION_HINTS = ("online", "web", "internet", "distance")


def _parse_meeting(meeting_time: dict) -> Meeting:
    building = str(meeting_time.get("buildingDescription") or meeting_time.get("building") or "").strip()
    room = str(meeting_time.get("room") or "").strip()
    location = " ".join(part for part in (building, room) if part)
    start = parse_hhmm(meeting_time.get("beginTime"))
    end = parse_hhmm(meeting_time.get("endTime"))
    looks_online = any(hint in location.lower() for hint in _ONLINE_LOCATION_HINTS)
    is_online = looks_online or (start is None and not room)
    return Meeting(
        days=days_from_flags({k: meeting_time.get(k) for k in _DAY_KEYS}),
        start_local=start,
        end_local=end,
        location=location,
        is_online=is_online,
        start_date=parse_date(meeting_time.get("startDate")),
        end_date=parse_date(meeting_time.get("endDate")),
    )


def _meetings_of(row: dict) -> tuple[Meeting, ...]:
    out: list[Meeting] = []
    for entry in row.get("meetingsFaculty") or []:
        meeting_time = entry.get("meetingTime") if isinstance(entry, dict) else None
        if isinstance(meeting_time, dict):
            out.append(_parse_meeting(meeting_time))
    return tuple(out)


def _status_of(row: dict) -> str:
    seats = int_or_none(row.get("seatsAvailable"))
    wait_capacity = int_or_none(row.get("waitCapacity")) or 0
    if not row.get("openSection"):
        return "closed"
    if seats is not None and seats <= 0:
        return "waitlist" if wait_capacity > 0 else "closed"
    return "open"


def _instructor_of(row: dict) -> str:
    names = [
        str(f.get("displayName")).strip()
        for f in row.get("faculty") or []
        if isinstance(f, dict) and f.get("displayName")
    ]
    return ", ".join(names)


def _parse_row(row: dict) -> ParsedSection:
    meetings = _meetings_of(row)
    method = row.get("instructionalMethodDescription") or row.get("instructionalMethod") or ""
    subject = str(row.get("subject") or "").strip()
    number = str(row.get("courseNumber") or "").strip()
    return ParsedSection(
        section_id=str(row.get("courseReferenceNumber", "")),
        status=_status_of(row),
        modality=normalize_modality(raw_tokens=[str(method)], meetings=meetings),
        title=str(row.get("courseTitle", "")),
        instructor=_instructor_of(row),
        meetings=meetings,
        seats_total=int_or_none(row.get("maximumEnrollment")),
        seats_used=int_or_none(row.get("enrollment")),
        course_code_as_listed=f"{subject} {number}".strip(),
    )


def _row_matches_campus(row: dict, codes: tuple[str, ...]) -> bool:
    """Keep rows whose meetings are at one of *codes*. Rows with no meetings are kept."""
    if not codes:
        return True
    campuses = {
        str(entry.get("meetingTime", {}).get("campus") or "").upper()
        for entry in row.get("meetingsFaculty") or []
        if isinstance(entry, dict)
    }
    campuses.discard("")
    if not campuses:
        return True
    return any(c in campuses for c in codes)


def _campus_codes(source: CollegeScheduleSource) -> tuple[str, ...]:
    raw = source.params.get("campus_codes", "")
    return tuple(code.strip().upper() for code in raw.split(",") if code.strip())
```

Then inside `search_course`, replace the loop body that builds `ParsedSection(...)` (the `for row in data:` block) with:

```python
            codes = _campus_codes(source)
            for row in data:
                if not isinstance(row, dict) or not _row_matches_campus(row, codes):
                    continue
                sections.append(_parse_row(row))
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/schedule/test_banner9_ssb.py -q`
Expected: PASS. (The pre-existing `test_search_course_returns_sections` still passes: rows without `meetingsFaculty` produce no meetings and `openSection` decides status.)

- [ ] **Step 6: Run the full suite and commit**

Run: `uv run pytest -q`
Expected: PASS.

```bash
git add -A src/schedule/banner9_ssb.py src/schedule/composite.py tests/schedule/test_banner9_ssb.py
git commit -m "feat(schedule): rename Banner SSB adapter to banner9_ssb and parse meetings, faculty, seats"
```

---

### Task 4: Colleague Self-Service adapter: rename, token, term resolution, meetings

**Files:**
- Rename: `src/schedule/banner_ellucian.py` → `src/schedule/colleague_selfservice.py`
- Rename: `tests/schedule/test_banner_ellucian.py` → `tests/schedule/test_colleague_selfservice.py`
- Create: `src/schedule/colleague_sections.py`
- Create: `tests/schedule/test_colleague_sections.py`
- Modify: `tests/schedule/test_pilot_provider.py`, `src/schedule/composite.py`, `CLAUDE.md`

**Interfaces:**
- Consumes: Task 1 models and normalize; `source.params["term_format"]` (optional; keys `{yyyy}`, `{yy}`, `{SEASON2}` = FA/SP/SU, `{SEASON1}` = F/S/U, `{SEASONSLASH}` = `/FA` style handled by writing `{yyyy}/{SEASON2}`), `source.params["location_match"]` (optional substring matched against a section's `LocationDisplay`/`Location` when `locations` is empty).
- Produces: `ColleagueSelfServiceProvider`; `colleague_sections.parse_section(body, wrapper) -> ParsedSection | None`; `colleague_sections.parse_meetings(body) -> tuple[Meeting, ...]`; `colleague_selfservice.format_term_code(term, fmt) -> str`; `colleague_selfservice.resolve_term_code(session, base, term, keyword, headers) -> str`; `colleague_selfservice.extract_request_token(html) -> str | None`.

Reference shape of one Colleague section (captured from `selfservice.sjeccd.edu`, Fall 2026):

```json
{
  "Synonym": "130980", "Number": "201", "CourseName": "MATH-020", "Title": "College Algebra - Liberal Arts",
  "SectionTitleDisplay": "College Algebra - Liberal Arts", "Location": "EVC", "LocationDisplay": "Evergreen Valley College",
  "AvailabilityStatusDisplay": "Waitlisted", "Available": 13, "Capacity": 42, "Enrolled": 29,
  "InstructionalMethodsDisplay": ["Lecture"], "FacultyDisplay": ["Sylvia R. Anderson"],
  "FormattedMeetingTimes": [{"DaysOfWeekDisplay": "M/W", "StartTime": "10:45:00", "EndTime": "12:05:00",
     "Days": [1, 3], "IsOnline": false, "BuildingDisplay": "MS3 Building", "RoomDisplay": "MS217",
     "StartDate": "2026-08-24T00:00:00-07:00", "EndDate": "2026-12-10T00:00:00-08:00",
     "InstructionalMethodDisplay": "Lecture"}],
  "Meetings": [{"InstructionalMethodCode": "02", "Days": [1, 3], "Room": "2MS3*MS217", "IsOnline": false}]
}
```

The `CatalogListing` view of `PostSearchCriteria` returns `"TermFilters": [{"Value": "2026FA", "Description": "Fall 2026 Regular"}, ...]`. Term code formats differ by district (`2026FA`, `2026/FA`, `2026F`, `26/FA`), so the adapter resolves them from this list and only uses `term_format` as an override.

- [ ] **Step 1: Rename the files**

```bash
git mv src/schedule/banner_ellucian.py src/schedule/colleague_selfservice.py
git mv tests/schedule/test_banner_ellucian.py tests/schedule/test_colleague_selfservice.py
sed -i '' 's/banner_ellucian/colleague_selfservice/g; s/BannerEllucianProvider/ColleagueSelfServiceProvider/g' src/schedule/colleague_selfservice.py src/schedule/composite.py tests/schedule/test_colleague_selfservice.py tests/schedule/test_pilot_provider.py
```

Run: `uv run pytest tests/schedule/test_colleague_selfservice.py tests/schedule/test_pilot_provider.py -q`
Expected: PASS.

- [ ] **Step 2: Write the failing section-parsing tests**

Create `tests/schedule/test_colleague_sections.py`:

```python
from __future__ import annotations

from datetime import date, time

from src.schedule.colleague_sections import parse_meetings, parse_section

_BODY = {
    "Synonym": "130980", "Number": "201", "CourseName": "MATH-020",
    "Title": "College Algebra - Liberal Arts", "SectionTitleDisplay": "College Algebra - Liberal Arts",
    "Location": "EVC", "LocationDisplay": "Evergreen Valley College",
    "AvailabilityStatusDisplay": "Waitlisted", "Available": 13, "Capacity": 42, "Enrolled": 29,
    "InstructionalMethodsDisplay": ["Lecture"], "FacultyDisplay": ["Sylvia R. Anderson"],
    "FormattedMeetingTimes": [{
        "DaysOfWeekDisplay": "M/W", "StartTime": "10:45:00", "EndTime": "12:05:00",
        "Days": [1, 3], "IsOnline": False, "BuildingDisplay": "MS3 Building", "RoomDisplay": "MS217",
        "StartDate": "2026-08-24T00:00:00-07:00", "EndDate": "2026-12-10T00:00:00-08:00",
        "InstructionalMethodDisplay": "Lecture"}],
    "Meetings": [{"InstructionalMethodCode": "02", "Days": [1, 3], "Room": "2MS3*MS217", "IsOnline": False}],
}

_BODY_ONLINE = {
    **_BODY, "Synonym": "130999", "AvailabilityStatusDisplay": "Open", "Available": 20, "Enrolled": 22,
    "InstructionalMethodsDisplay": ["Online"],
    "FormattedMeetingTimes": [{"Days": [], "IsOnline": True, "StartTime": None, "EndTime": None,
        "BuildingDisplay": "", "RoomDisplay": "", "StartDate": "2026-08-24T00:00:00-07:00",
        "EndDate": "2026-12-10T00:00:00-08:00", "InstructionalMethodDisplay": "Online"}],
    "Meetings": [],
}


def test_parse_meetings_from_formatted_times():
    (m,) = parse_meetings(_BODY)
    assert m.days == ("M", "W")
    assert m.start_local == time(10, 45)
    assert m.end_local == time(12, 5)
    assert m.location == "MS3 Building MS217"
    assert m.is_online is False
    assert m.start_date == date(2026, 8, 24)
    assert m.end_date == date(2026, 12, 10)


def test_parse_meetings_falls_back_to_raw_meetings():
    body = {**_BODY, "FormattedMeetingTimes": None}
    (m,) = parse_meetings(body)
    assert m.days == ("M", "W")
    assert m.location == "2MS3*MS217"
    assert m.start_local is None


def test_parse_meetings_empty():
    assert parse_meetings({**_BODY, "FormattedMeetingTimes": [], "Meetings": []}) == ()


def test_parse_section_in_person_waitlisted():
    s = parse_section(_BODY, wrapper=None)
    assert s is not None
    assert s.section_id == "130980"
    assert s.status == "waitlist"
    assert s.modality == "in_person"
    assert s.title == "College Algebra - Liberal Arts"
    assert s.instructor == "Sylvia R. Anderson"
    assert s.seats_total == 42
    assert s.seats_used == 29
    assert s.course_code_as_listed == "MATH-020"
    assert len(s.meetings) == 1


def test_parse_section_online_async():
    s = parse_section(_BODY_ONLINE, wrapper=None)
    assert s is not None
    assert s.modality == "async_online"
    assert s.status == "open"


def test_parse_section_seats_used_derived_when_enrolled_missing():
    body = {k: v for k, v in _BODY.items() if k != "Enrolled"}
    s = parse_section(body, wrapper=None)
    assert s is not None
    assert s.seats_used == 29  # Capacity 42 - Available 13


def test_parse_section_instructor_from_wrapper_wins():
    s = parse_section(_BODY, wrapper={"FacultyDisplay": ["Wrapped Name"]})
    assert s is not None
    assert s.instructor == "Wrapped Name"


def test_parse_section_without_id_returns_none():
    body = {k: v for k, v in _BODY.items() if k not in ("Synonym", "Number", "Id")}
    assert parse_section(body, wrapper=None) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/schedule/test_colleague_sections.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.schedule.colleague_sections'`.

- [ ] **Step 4: Create the section parsing module**

Create `src/schedule/colleague_sections.py`:

```python
"""Parse Colleague Self-Service section JSON into ParsedSection and Meeting."""
from __future__ import annotations

from .models import Meeting, ParsedSection
from .normalize import (
    days_from_indices,
    int_or_none,
    normalize_modality,
    normalize_status,
    parse_date,
    parse_hhmm,
)


def _first_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return None


def _meeting_from_formatted(entry: dict) -> Meeting:
    building = str(entry.get("BuildingDisplay") or "").strip()
    room = str(entry.get("RoomDisplay") or "").strip()
    return Meeting(
        days=days_from_indices(entry.get("Days") or []),
        start_local=parse_hhmm(entry.get("StartTime")),
        end_local=parse_hhmm(entry.get("EndTime")),
        location=" ".join(part for part in (building, room) if part),
        is_online=bool(entry.get("IsOnline")),
        start_date=parse_date(entry.get("StartDate")),
        end_date=parse_date(entry.get("EndDate")),
    )


def _meeting_from_raw(entry: dict) -> Meeting:
    return Meeting(
        days=days_from_indices(entry.get("Days") or []),
        location=str(entry.get("Room") or "").strip(),
        is_online=bool(entry.get("IsOnline")),
        start_date=parse_date(entry.get("StartDate")),
        end_date=parse_date(entry.get("EndDate")),
    )


def parse_meetings(body: dict) -> tuple[Meeting, ...]:
    formatted = body.get("FormattedMeetingTimes")
    if isinstance(formatted, list) and formatted:
        return tuple(_meeting_from_formatted(e) for e in formatted if isinstance(e, dict))
    raw = body.get("Meetings")
    if isinstance(raw, list) and raw:
        return tuple(_meeting_from_raw(e) for e in raw if isinstance(e, dict))
    return ()


def _method_tokens(body: dict, meetings: tuple[Meeting, ...]) -> list[str]:
    tokens: list[str] = []
    methods = body.get("InstructionalMethodsDisplay")
    if isinstance(methods, list):
        tokens.extend(str(m) for m in methods)
    elif isinstance(methods, str):
        tokens.append(methods)
    for entry in body.get("FormattedMeetingTimes") or []:
        if isinstance(entry, dict) and entry.get("InstructionalMethodDisplay"):
            tokens.append(str(entry["InstructionalMethodDisplay"]))
    return tokens


def _instructor(*, wrapper: dict | None, body: dict) -> str:
    for source in (wrapper or {}, body):
        faculty = source.get("FacultyDisplay")
        if isinstance(faculty, list):
            names = [str(name).strip() for name in faculty if str(name).strip()]
            if names:
                return ", ".join(names)
        if isinstance(faculty, str) and faculty.strip():
            return faculty.strip()
    return ""


def _seats_used(body: dict) -> int | None:
    enrolled = int_or_none(body.get("Enrolled"))
    if enrolled is not None:
        return enrolled
    capacity = int_or_none(body.get("Capacity"))
    available = int_or_none(body.get("Available"))
    if capacity is None or available is None:
        return None
    return capacity - available


def parse_section(body: dict, wrapper: dict | None) -> ParsedSection | None:
    section_id = _first_str(body.get("Synonym"), body.get("Number"), body.get("Id"))
    if section_id is None:
        return None
    meetings = parse_meetings(body)
    title = _first_str(body.get("Title"), body.get("SectionTitleDisplay"), body.get("CourseName")) or ""
    return ParsedSection(
        section_id=section_id,
        status=normalize_status(
            _first_str(body.get("AvailabilityStatusDisplay"), body.get("AvailabilityStatus"))
        ),
        modality=normalize_modality(raw_tokens=_method_tokens(body, meetings), meetings=meetings),
        title=title,
        instructor=_instructor(wrapper=wrapper, body=body),
        meetings=meetings,
        seats_total=int_or_none(body.get("Capacity")),
        seats_used=_seats_used(body),
        course_code_as_listed=_first_str(body.get("CourseName")) or "",
    )
```

- [ ] **Step 5: Run the section tests**

Run: `uv run pytest tests/schedule/test_colleague_sections.py -q`
Expected: PASS.

- [ ] **Step 6: Write the failing adapter tests**

Append to `tests/schedule/test_colleague_selfservice.py`:

```python
from types import MappingProxyType  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

from src.schedule.colleague_selfservice import (  # noqa: E402
    extract_request_token,
    format_term_code,
    resolve_term_code,
)
from src.schedule.term import parse_term_label  # noqa: E402

_HTML = '<form><input name="__RequestVerificationToken" type="hidden" value="CfDJ8ABC" /></form>'
_HTML_REVERSED = '<input type="hidden" value="CfDJ8XYZ" name="__RequestVerificationToken">'


def test_extract_request_token():
    assert extract_request_token(_HTML) == "CfDJ8ABC"
    assert extract_request_token(_HTML_REVERSED) == "CfDJ8XYZ"
    assert extract_request_token("<html></html>") is None


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("{yyyy}{SEASON2}", "2026FA"),
        ("{yyyy}/{SEASON2}", "2026/FA"),
        ("{yyyy}{SEASON1}", "2026F"),
        ("{yy}/{SEASON2}", "26/FA"),
    ],
)
def test_format_term_code(fmt, expected):
    assert format_term_code(parse_term_label("Fall 2026"), fmt) == expected


def test_format_term_code_seasons():
    assert format_term_code(parse_term_label("Spring 2027"), "{yyyy}{SEASON2}") == "2027SP"
    assert format_term_code(parse_term_label("Summer 2026"), "{yyyy}{SEASON1}") == "2026U"


def _resp(json_data, text="", status=200):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = json_data
    r.text = text
    r.url = "https://example.edu/Student/Courses/PostSearchCriteria"
    r.raise_for_status = MagicMock()
    return r


def test_resolve_term_code_matches_description():
    session = MagicMock(spec=requests.Session)
    session.post.return_value = _resp(
        {"TermFilters": [{"Value": "2026FA", "Description": "Fall 2026 Regular"},
                         {"Value": "2026SU", "Description": "Summer 2026 Regular"}]}
    )
    code = resolve_term_code(session, "https://example.edu", parse_term_label("Fall 2026"), keyword="MATH 1", headers={})
    assert code == "2026FA"


def test_resolve_term_code_missing_raises():
    session = MagicMock(spec=requests.Session)
    session.post.return_value = _resp({"TermFilters": [{"Value": "2026SU", "Description": "Summer 2026"}]})
    with pytest.raises(ValueError, match="Fall 2026"):
        resolve_term_code(session, "https://example.edu", parse_term_label("Fall 2026"), keyword="MATH 1", headers={})


def test_supports_source_with_empty_locations():
    src = CollegeScheduleSource(cc_id=73, cc_name="Napa Valley College", system="colleague_selfservice",
                                base_url="https://colss-prod.ec.napavalley.edu", locations=())
    assert ColleagueSelfServiceProvider().supports_source(src)


def test_search_uses_term_format_override_and_sends_token():
    src = CollegeScheduleSource(
        cc_id=69, cc_name="Chaffey College", system="colleague_selfservice",
        base_url="https://colss-prod.ec.chaffey.edu", locations=(),
        params=MappingProxyType({"term_format": "{yyyy}/{SEASON2}"}),
    )
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = _resp({}, text=_HTML)
    listing = {"TotalPages": 1, "Sections": [{
        "Synonym": "1", "CourseName": "MATH-25", "Title": "Calc", "AvailabilityStatusDisplay": "Open",
        "Capacity": 30, "Enrolled": 10, "InstructionalMethodsDisplay": ["Lecture"], "FacultyDisplay": ["A B"],
        "FormattedMeetingTimes": [{"Days": [2, 4], "StartTime": "09:00:00", "EndTime": "10:15:00", "IsOnline": False,
                                    "BuildingDisplay": "H", "RoomDisplay": "101"}],
        "Course": {"SubjectCode": "MATH", "Number": "25"}}]}
    session.post.return_value = _resp(listing)
    provider = ColleagueSelfServiceProvider(session=session)
    result = provider.search_course(source=src, term=parse_term_label("Fall 2026"), course_code="MATH 25")
    assert result.offered is True
    assert result.sections[0].meetings[0].days == ("T", "R")
    assert result.sections[0].seats_used == 10
    payload = session.post.call_args_list[0].kwargs["json"]
    assert payload["terms"] == ["2026/FA"]
    assert payload["locations"] == []
    assert session.headers["__RequestVerificationToken"] == "CfDJ8ABC"


def test_search_filters_by_location_match_when_locations_empty():
    src = CollegeScheduleSource(
        cc_id=67, cc_name="West Hills College Coalinga", system="colleague_selfservice",
        base_url="https://ellucianssui.whccd.edu", locations=(),
        params=MappingProxyType({"term_format": "{yyyy}/{SEASON2}", "location_match": "Coalinga"}),
    )
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = _resp({}, text=_HTML)
    base = {"CourseName": "MATH-25", "Title": "Calc", "AvailabilityStatusDisplay": "Open",
            "Course": {"SubjectCode": "MATH", "Number": "25"}, "FormattedMeetingTimes": []}
    listing = {"TotalPages": 1, "Sections": [
        {**base, "Synonym": "1", "LocationDisplay": "West Hills College Coalinga"},
        {**base, "Synonym": "2", "LocationDisplay": "West Hills College Lemoore"}]}
    session.post.return_value = _resp(listing)
    result = ColleagueSelfServiceProvider(session=session).search_course(
        source=src, term=parse_term_label("Fall 2026"), course_code="MATH 25")
    assert [s.section_id for s in result.sections] == ["1"]
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `uv run pytest tests/schedule/test_colleague_selfservice.py -q`
Expected: FAIL with `ImportError: cannot import name 'extract_request_token'`.

- [ ] **Step 8: Implement token, term resolution, empty locations, and delegate parsing**

In `src/schedule/colleague_selfservice.py`:

1. Replace the import block at the top with:

```python
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from .colleague_sections import parse_section
from .models import CollegeScheduleSource, CourseAvailability, ParsedSection
from .term import ParsedTerm
```

2. Add after the constants (below `_DEBUG_RAW_SUMMARY`):

```python
_TOKEN_RE_NAME_FIRST = re.compile(
    r'name="__RequestVerificationToken"[^>]*?value="([^"]+)"', re.IGNORECASE
)
_TOKEN_RE_VALUE_FIRST = re.compile(
    r'value="([^"]+)"[^>]*?name="__RequestVerificationToken"', re.IGNORECASE
)
_SEASON2 = {"spring": "SP", "summer": "SU", "fall": "FA"}
_SEASON1 = {"spring": "S", "summer": "U", "fall": "F"}
_JSON_HEADERS = {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}


def extract_request_token(html: str) -> str | None:
    for pattern in (_TOKEN_RE_NAME_FIRST, _TOKEN_RE_VALUE_FIRST):
        match = pattern.search(html)
        if match:
            return match.group(1)
    return None


def format_term_code(term: ParsedTerm, fmt: str) -> str:
    return (
        fmt.replace("{yyyy}", str(term.year))
        .replace("{yy}", str(term.year)[-2:])
        .replace("{SEASON2}", _SEASON2[term.season])
        .replace("{SEASON1}", _SEASON1[term.season])
    )


def resolve_term_code(
    session: requests.Session,
    base_root: str,
    term: ParsedTerm,
    *,
    keyword: str,
    headers: dict[str, str],
) -> str:
    """Ask the portal for its term list (CatalogListing view) and match by label."""
    response = session.post(
        f"{base_root}/Student/Courses/PostSearchCriteria",
        json={
            "keyword": keyword,
            "pageNumber": 1,
            "quantityPerPage": 1,
            "searchResultsView": "CatalogListing",
            "terms": [],
            "locations": [],
        },
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    needle = term.label.lower()
    for entry in _safe_json(response).get("TermFilters") or []:
        if not isinstance(entry, dict):
            continue
        description = str(entry.get("Description") or entry.get("Text") or "").lower()
        if needle in description and entry.get("Value"):
            return str(entry["Value"])
    raise ValueError(f"Term {term.label!r} not found in Colleague TermFilters at {base_root}")
```

3. Replace the `supports_source` method body with:

```python
        return source.system == "colleague_selfservice"
```

4. In `search_course`, replace the block from `term_code = _term_to_banner_code(term)` through `locations = source.locations` with:

```python
        requested_identity = _parse_requested_course_identity(course_code)
        base_root = _base_root_from_url(source.base_url)
        bootstrap_url = f"{base_root}/Student/Courses/Search"
        search_url = f"{base_root}/Student/Courses/PostSearchCriteria"
        sections_url = f"{base_root}/Student/Courses/Sections"
        locations = source.locations
        location_match = source.params.get("location_match", "").strip().lower()
        self._bootstrap(bootstrap_url, course_code=course_code, locations=locations)
        term_code = self._term_code(base_root, term, source=source, keyword=course_code)
```

and add these two methods to the class:

```python
    def _bootstrap(self, bootstrap_url: str, *, course_code: str, locations: tuple[str, ...]) -> None:
        params: dict[str, str] = {"keyword": course_code}
        if locations:
            params["locations"] = locations[0]
        response = self._session.get(bootstrap_url, params=params, timeout=20)
        response.raise_for_status()
        token = extract_request_token(response.text)
        if token:
            self._session.headers["__RequestVerificationToken"] = token
        for key, value in _JSON_HEADERS.items():
            self._session.headers.setdefault(key, value)

    def _term_code(
        self, base_root: str, term: ParsedTerm, *, source: CollegeScheduleSource, keyword: str
    ) -> str:
        fmt = source.params.get("term_format")
        if fmt:
            return format_term_code(term, fmt)
        cache_key = (base_root, term.label)
        if cache_key not in self._term_cache:
            self._term_cache[cache_key] = resolve_term_code(
                self._session, base_root, term, keyword=keyword, headers=dict(self._session.headers)
            )
        return self._term_cache[cache_key]
```

and change `__init__` to:

```python
    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._term_cache: dict[tuple[str, str], str] = {}
```

5. Inside the `for keyword in _keyword_variants(course_code)[:_MAX_KEYWORD_VARIANTS]:` loop, delete the `bootstrap = self._session.get(...)` call and its `bootstrap.raise_for_status()` (bootstrap now happens once, above the loop).

6. Change `_search_section_listing` and `_fetch_sections_from_catalog`/`_parse_sections_response` so that every place that calls `_parse_section(raw_section, wrapper=None)` or `_parse_section(section_body, wrapper=wrapped)` calls `parse_section(...)` from `colleague_sections` instead, then apply the location filter. Add this helper at module level and use it in `_parse_section_listing` and `_parse_sections_response` right after a section is parsed:

```python
def _location_ok(raw_row: dict[str, object], location_match: str) -> bool:
    if not location_match:
        return True
    haystack = " ".join(
        str(raw_row.get(key) or "") for key in ("LocationDisplay", "Location", "LocationCode")
    ).lower()
    return location_match in haystack
```

Thread `location_match: str` as a keyword argument through `_search_section_listing`, `_parse_section_listing`, `_fetch_sections_from_catalog`, and `_parse_sections_response` (default `""`), and pass `location_match=location_match` from `search_course`. In `_parse_section_listing` the row check becomes:

```python
        if not _location_ok(raw_section, location_match):
            stats.dropped_nonmatch += 1
            continue
        section = parse_section(raw_section, wrapper=None)
```

and in `_parse_sections_response`:

```python
            if not _location_ok(section_body, location_match):
                stats.dropped_nonmatch += 1
                continue
            section = parse_section(section_body, wrapper=wrapped)
```

7. Delete from this file: `_parse_section`, `_normalize_status`, `_normalize_modality`, `_normalize_instructor`, `_term_to_banner_code`, and the `_STATUS_MAP` constant. Keep `_first_str` (still used by `_extract_catalog_identity`). Keep `ParsedSection` in the imports only if still referenced; remove it otherwise.

- [ ] **Step 9: Repair the pilot-provider tests for the new call order**

`tests/schedule/test_pilot_provider.py` builds fake sessions with ordered `get`/`post` side effects. The adapter now does one bootstrap `GET` before the loop and, when no `term_format` param is set, one extra `POST` (CatalogListing for term resolution) before the first search. Open that file and, for every fake session:

- Keep exactly one bootstrap `GET` response at the front of `get.side_effect`, and remove the per-keyword duplicates (previously one per keyword variant).
- Insert `_resp({"TermFilters": [{"Value": "2026SU", "Description": "Summer 2026"}]})`-style response as the first `post.side_effect` entry, using the term label each test passes.

Run: `uv run pytest tests/schedule/test_pilot_provider.py -q` and fix any remaining ordering assertion by reading the failure's call list. Do not change what the tests assert about sections; only the fake response ordering changes.

- [ ] **Step 10: Run the adapter tests, then the full suite**

Run: `uv run pytest tests/schedule/test_colleague_selfservice.py tests/schedule/test_colleague_sections.py tests/schedule/test_pilot_provider.py -q`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 11: Update CLAUDE.md scraper list**

In `CLAUDE.md` replace the two lines

```
- `banner_ellucian.py` — Banner/Ellucian (majority of CA CCs)
- `banner_ssb_classic.py` — Banner SSB Classic variant (MtSAC, CCSF)
```

with

```
- `colleague_selfservice.py` — Ellucian Colleague Self-Service (`/Student/Courses`, ~30 CA CCs); term codes resolved from the portal's `TermFilters`, per-district overrides in `params`
- `colleague_sections.py` — section/meeting parsing for Colleague JSON
- `banner9_ssb.py` — Banner 9 StudentRegistrationSsb (~14 CA CCs); term codes resolved via `getTerms`, optional `params.campus_codes` for shared district portals
- `normalize.py` — shared day/time/modality/status normalization used by every adapter
```

- [ ] **Step 12: Commit**

```bash
git add -A src/schedule tests/schedule CLAUDE.md
git commit -m "refactor(schedule): rename Colleague adapter, resolve term codes, parse meetings and seats"
```

---

### Task 5: Colleague discovery script

**Files:**
- Create: `scripts/discover_colleague.py`
- Create: `scripts/__init__.py` (empty)
- Test: `tests/scripts/test_discover_colleague.py`, `tests/scripts/__init__.py` (empty)

**Interfaces:**
- Consumes: `extract_request_token`, `_safe_json` semantics from Task 4 (the script re-implements the tiny JSON guard to avoid importing private names).
- Produces: `discover(base_root: str, session: requests.Session, keyword: str = "MATH 1") -> dict` returning `{"base_root", "terms": [{"value", "description"}], "locations": [{"value", "description"}], "suggested_term_format": str | None}`; CLI `uv run python -m scripts.discover_colleague https://selfservice.sjeccd.edu`.

The script exists so the catalog entries in Task 6 are filled from what each portal reports rather than guessed, and it is the seed of the Phase 4 onboarding probe.

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/test_discover_colleague.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

import requests

from scripts.discover_colleague import discover, suggest_term_format


def _resp(json_data=None, text=""):
    r = MagicMock(spec=requests.Response)
    r.status_code = 200
    r.json.return_value = json_data if json_data is not None else {}
    r.text = text
    r.raise_for_status = MagicMock()
    return r


def test_suggest_term_format():
    assert suggest_term_format("2026FA", "Fall 2026") == "{yyyy}{SEASON2}"
    assert suggest_term_format("2026/FA", "Fall 2026") == "{yyyy}/{SEASON2}"
    assert suggest_term_format("2026F", "Fall 2026") == "{yyyy}{SEASON1}"
    assert suggest_term_format("26/FA", "Fall 2026") == "{yy}/{SEASON2}"
    assert suggest_term_format("FA26", "Fall 2026") is None


def test_discover_collects_terms_locations_and_format():
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = _resp(text='<input name="__RequestVerificationToken" value="tok">')
    session.post.return_value = _resp({
        "TermFilters": [{"Value": "2026FA", "Description": "Fall 2026 Regular"}],
        "LocationFilters": [{"Value": "EVC", "Description": "Evergreen Valley College"},
                            {"Value": "SJCC", "Description": "San Jose City College"}],
    })
    out = discover("https://selfservice.sjeccd.edu", session)
    assert out["terms"] == [{"value": "2026FA", "description": "Fall 2026 Regular"}]
    assert [loc["value"] for loc in out["locations"]] == ["EVC", "SJCC"]
    assert out["suggested_term_format"] == "{yyyy}{SEASON2}"
    assert session.headers["__RequestVerificationToken"] == "tok"


def test_discover_handles_missing_filters():
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = _resp(text="")
    session.post.return_value = _resp({})
    out = discover("https://example.edu", session)
    assert out["terms"] == []
    assert out["locations"] == []
    assert out["suggested_term_format"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts'`.

- [ ] **Step 3: Write the script**

Create empty `scripts/__init__.py` and `tests/scripts/__init__.py`. Create `scripts/discover_colleague.py`:

```python
"""Print a Colleague Self-Service portal's term codes and location codes.

Usage:
    uv run python -m scripts.discover_colleague https://selfservice.sjeccd.edu [KEYWORD]

The output is JSON you paste into src/schedule/data/colleges.json `params` and
`locations`. This is read-only against the portal: one GET and one POST.
"""
from __future__ import annotations

import json
import re
import sys

import requests

from src.schedule.colleague_selfservice import extract_request_token

_UA = "Mozilla/5.0 (compatible; cc-course-finder discovery; +https://github.com/FYC23/CC-course-finder)"
_SEASON2 = {"fall": "FA", "spring": "SP", "summer": "SU"}
_SEASON1 = {"fall": "F", "spring": "S", "summer": "U"}


def suggest_term_format(value: str, description: str) -> str | None:
    """Infer a `term_format` template from one (code, label) pair, or None if no template fits."""
    match = re.match(r"^(Spring|Summer|Fall)\s+(\d{4})", description, re.IGNORECASE)
    if not match:
        return None
    season = match.group(1).lower()
    year = match.group(2)
    candidates = {
        "{yyyy}{SEASON2}": f"{year}{_SEASON2[season]}",
        "{yyyy}/{SEASON2}": f"{year}/{_SEASON2[season]}",
        "{yyyy}{SEASON1}": f"{year}{_SEASON1[season]}",
        "{yy}/{SEASON2}": f"{year[-2:]}/{_SEASON2[season]}",
        "{yy}{SEASON2}": f"{year[-2:]}{_SEASON2[season]}",
    }
    for template, rendered in candidates.items():
        if rendered == value:
            return template
    return None


def _filters(payload: dict, key: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for entry in payload.get(key) or []:
        if isinstance(entry, dict) and entry.get("Value"):
            out.append({
                "value": str(entry["Value"]),
                "description": str(entry.get("Description") or entry.get("Text") or ""),
            })
    return out


def discover(base_root: str, session: requests.Session, keyword: str = "MATH 1") -> dict:
    session.headers.setdefault("User-Agent", _UA)
    page = session.get(f"{base_root}/Student/Courses/Search", params={"keyword": keyword}, timeout=25)
    page.raise_for_status()
    token = extract_request_token(page.text)
    if token:
        session.headers["__RequestVerificationToken"] = token
    response = session.post(
        f"{base_root}/Student/Courses/PostSearchCriteria",
        json={"keyword": keyword, "pageNumber": 1, "quantityPerPage": 1,
              "searchResultsView": "CatalogListing", "terms": [], "locations": []},
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
        timeout=25,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    terms = _filters(payload, "TermFilters")
    suggested = next(
        (fmt for t in terms if (fmt := suggest_term_format(t["value"], t["description"]))), None
    )
    return {
        "base_root": base_root,
        "terms": terms,
        "locations": _filters(payload, "LocationFilters"),
        "suggested_term_format": suggested,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    keyword = argv[2] if len(argv) > 2 else "MATH 1"
    result = discover(argv[1].rstrip("/"), requests.Session(), keyword=keyword)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/scripts -q`
Expected: PASS.

- [ ] **Step 5: Run it against one live portal to confirm it works end to end**

Run: `uv run python -m scripts.discover_colleague https://selfservice.sjeccd.edu`
Expected: JSON with a `terms` list containing a `2026FA`-style value and `suggested_term_format` = `"{yyyy}{SEASON2}"`. (Locations may be empty for this host; that is fine.)

- [ ] **Step 6: Commit**

```bash
git add scripts tests/scripts
git commit -m "feat(schedule): add Colleague portal discovery script for term and location codes"
```

---

### Task 6: Catalog data: fix stale entries and add Banner 9 and Colleague colleges

**Files:**
- Modify: `src/schedule/data/colleges.json`
- Modify: `README.md` (supported colleges table)

**Interfaces:**
- Consumes: Task 2 schema, Task 3 `campus_codes`, Task 4 `term_format` and `location_match`, Task 5 script.

Sources for every value below are the survey CSV rows (column `evidence`). Where a shared district portal needs a location code that the survey did not confirm, the step says to run the discovery script and use what it prints.

- [ ] **Step 1: Replace the catalog file**

Write `src/schedule/data/colleges.json` as:

```json
[
  {"cc_id": 2, "cc_name": "Evergreen Valley College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.sjeccd.edu", "locations": ["EVC"],
   "source_url": "https://www.evc.edu/current-students/schedule-of-classes",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 71"}},
  {"cc_id": 136, "cc_name": "San Jose City College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.sjeccd.edu", "locations": ["SJCC"],
   "source_url": "https://www.sjcc.edu/academics/schedule-of-classes",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 71"}},
  {"cc_id": 80, "cc_name": "West Valley College", "system": "wvm_static",
   "base_url": "https://schedule.wvm.edu", "locations": ["WVC"],
   "source_url": "https://www.westvalley.edu/academics/schedule-of-classes/"},
  {"cc_id": 32, "cc_name": "Mission College", "system": "wvm_static",
   "base_url": "https://schedule.wvm.edu", "locations": ["MC"],
   "source_url": "https://missioncollege.edu/schedule/",
   "note": "Same static JSON as West Valley. Confirm the campus code by inspecting the campus field in schedule.wvm.edu's section JSON; if it is not MC, correct it and the live smoke test in step 4 will show sections.",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 114, "cc_name": "Diablo Valley College", "system": "vsb_4cd",
   "base_url": "https://vsb.4cd.edu", "locations": ["DVC"],
   "source_url": "https://www.dvc.edu/enrollment/schedule-of-classes.html"},
  {"cc_id": 61, "cc_name": "Los Medanos College", "system": "vsb_4cd",
   "base_url": "https://vsb.4cd.edu", "locations": ["LMC"],
   "source_url": "https://www.losmedanos.edu/enrollment/schedule.aspx"},
  {"cc_id": 28, "cc_name": "Contra Costa College", "system": "vsb_4cd",
   "base_url": "https://vsb.4cd.edu", "locations": ["CCC"],
   "source_url": "https://www.contracosta.edu/class-schedule/"},
  {"cc_id": 62, "cc_name": "Mount San Antonio College", "system": "banner9_ssb",
   "base_url": "https://prodrg.mtsac.edu", "locations": [],
   "source_url": "https://www.mtsac.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 180"}},
  {"cc_id": 33, "cc_name": "City College of San Francisco", "system": "banner9_ssb",
   "base_url": "https://ssb1.ccsf.edu:8105", "locations": [],
   "source_url": "https://www.ccsf.edu/academics/schedule-of-classes",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 5, "cc_name": "College of San Mateo", "system": "banner9_ssb",
   "base_url": "https://phx-ban-apps.smccd.edu", "locations": [],
   "params": {"campus_codes": "CSM"},
   "source_url": "https://collegeofsanmateo.edu/schedule/",
   "note": "SMCCD shared Banner 9 portal; campus code to confirm via one live query (campusDescription distinguishes CSM/Skyline/Canada).",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 110, "cc_name": "Allan Hancock College", "system": "banner9_ssb",
   "base_url": "https://ssb.hancockcollege.edu", "locations": [],
   "source_url": "https://www.hancockcollege.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 84, "cc_name": "Bakersfield College", "system": "banner9_ssb",
   "base_url": "https://reg-prod.ec.kccd.edu", "locations": [],
   "params": {"campus_codes": "BB,BD,BS,BW"},
   "source_url": "https://www.bakersfieldcollege.edu/schedule/",
   "note": "Kern CCD shared portal. Campus codes start with B for Bakersfield; confirm the full list from meetingTime.campus values in one live query.",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 9, "cc_name": "Cerro Coso Community College", "system": "banner9_ssb",
   "base_url": "https://reg-prod.ec.kccd.edu", "locations": [],
   "params": {"campus_codes": "CR,CU,CT,CS,CV,CW"},
   "source_url": "https://www.cerrocoso.edu/schedule/",
   "note": "Kern CCD shared portal. Codes from survey notes; CR = Ridgecrest main.",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 125, "cc_name": "Porterville College", "system": "banner9_ssb",
   "base_url": "https://reg-prod.ec.kccd.edu", "locations": [],
   "params": {"campus_codes": "PC,PP"},
   "source_url": "https://www.portervillecollege.edu/schedule/",
   "note": "Kern CCD shared portal. Confirm codes from meetingTime.campus in one live query.",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 20, "cc_name": "Barstow Community College", "system": "banner9_ssb",
   "base_url": "https://ssbprod2.barstow.edu:8443", "locations": [],
   "source_url": "https://www.barstow.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 153, "cc_name": "Compton College", "system": "banner9_ssb",
   "base_url": "https://cmptn-prod-pxes02.banner.elluciancloud.com:8090", "locations": [],
   "source_url": "https://www.compton.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 100"}},
  {"cc_id": 16, "cc_name": "Cuesta College", "system": "banner9_ssb",
   "base_url": "https://ssb2.cuesta.edu", "locations": [],
   "source_url": "https://www.cuesta.edu/student/studentservices/admrec/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 122, "cc_name": "Feather River College", "system": "banner9_ssb",
   "base_url": "https://sfsc-prod-pxes02.banner.elluciancloud.com:8090", "locations": [],
   "source_url": "https://www.frc.edu/schedule/",
   "note": "Use the elluciancloud host directly; the college CMS lowercases paths and breaks Banner routing.",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 93, "cc_name": "Sierra College", "system": "banner9_ssb",
   "base_url": "https://ss.oci.sierracollege.edu", "locations": [],
   "source_url": "https://www.sierracollege.edu/students/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 94, "cc_name": "Solano Community College", "system": "banner9_ssb",
   "base_url": "https://reg-prod.solano.elluciancloud.com:8118", "locations": [],
   "source_url": "https://welcome.solano.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 8, "cc_name": "Butte College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.butte.edu", "locations": [],
   "source_url": "https://www.butte.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 1"}},
  {"cc_id": 41, "cc_name": "Cabrillo College", "system": "colleague_selfservice",
   "base_url": "https://cabrillo-ss.colleague.elluciancloud.com", "locations": [],
   "source_url": "https://www.cabrillo.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 1"}},
  {"cc_id": 69, "cc_name": "Chaffey College", "system": "colleague_selfservice",
   "base_url": "https://colss-prod.ec.chaffey.edu", "locations": [],
   "params": {"term_format": "{yyyy}/{SEASON2}"},
   "source_url": "https://www.chaffey.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 1"}},
  {"cc_id": 150, "cc_name": "Clovis Community College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.scccd.edu", "locations": [],
   "params": {"location_match": "Clovis"},
   "source_url": "https://www.cloviscollege.edu/schedule/",
   "note": "SCCCD shared portal (Fresno City, Reedley, Clovis, Madera). Replace location_match with a `locations` code if the discovery script prints one.",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 1"}},
  {"cc_id": 35, "cc_name": "Fresno City College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.scccd.edu", "locations": [],
   "params": {"location_match": "Fresno City"},
   "source_url": "https://www.fresnocitycollege.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 1"}},
  {"cc_id": 200, "cc_name": "Madera Community College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.scccd.edu", "locations": [],
   "params": {"location_match": "Madera"},
   "source_url": "https://www.maderacollege.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH 1"}},
  {"cc_id": 140, "cc_name": "College of the Canyons", "system": "colleague_selfservice",
   "base_url": "https://selfservice.canyons.edu", "locations": [],
   "source_url": "https://www.canyons.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 99, "cc_name": "Cuyamaca College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.gcccd.edu", "locations": ["CC"],
   "source_url": "https://www.cuyamaca.edu/schedule/",
   "note": "GCCCD shared portal; CC = Cuyamaca, GC = Grossmont.",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 106, "cc_name": "Grossmont College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.gcccd.edu", "locations": ["GC"],
   "source_url": "https://www.grossmont.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 103, "cc_name": "El Camino College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.elcamino.edu", "locations": [],
   "source_url": "https://www.elcamino.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 123, "cc_name": "Hartnell College", "system": "colleague_selfservice",
   "base_url": "https://stuserv.hartnell.edu", "locations": [],
   "source_url": "https://www.hartnell.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 73, "cc_name": "Napa Valley College", "system": "colleague_selfservice",
   "base_url": "https://colss-prod.ec.napavalley.edu", "locations": [],
   "source_url": "https://www.napavalley.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 48, "cc_name": "Ohlone College", "system": "colleague_selfservice",
   "base_url": "https://selfservice.ohlone.edu:8443", "locations": [],
   "source_url": "https://www.ohlone.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 14, "cc_name": "Rancho Santiago College", "system": "colleague_selfservice",
   "base_url": "https://colss-prod.cloud.rsccd.edu", "locations": [],
   "params": {"location_match": "Santa Ana"},
   "source_url": "https://www.sac.edu/schedule/",
   "note": "RSCCD shared portal (Santa Ana College, Santiago Canyon College). ASSIST's 'Rancho Santiago College' is Santa Ana College.",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 38, "cc_name": "Shasta College", "system": "colleague_selfservice",
   "base_url": "https://mysc.shastacollege.edu", "locations": [],
   "params": {"term_format": "{yyyy}{SEASON1}"},
   "source_url": "https://www.shastacollege.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 138, "cc_name": "Southwestern College", "system": "colleague_selfservice",
   "base_url": "https://collselfserv.swccd.edu", "locations": [],
   "params": {"term_format": "{yy}/{SEASON2}"},
   "source_url": "https://www.swccd.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 19, "cc_name": "Victor Valley College", "system": "colleague_selfservice",
   "base_url": "https://vvc-ss.colleague.elluciancloud.com", "locations": [],
   "source_url": "https://www.vvc.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 67, "cc_name": "West Hills College Coalinga", "system": "colleague_selfservice",
   "base_url": "https://ellucianssui.whccd.edu", "locations": [],
   "params": {"term_format": "{yyyy}/{SEASON2}", "location_match": "Coalinga"},
   "source_url": "https://www.westhillscollege.com/coalinga/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 146, "cc_name": "West Hills College Lemoore", "system": "colleague_selfservice",
   "base_url": "https://ellucianssui.whccd.edu", "locations": [],
   "params": {"term_format": "{yyyy}/{SEASON2}", "location_match": "Lemoore"},
   "source_url": "https://www.westhillscollege.com/lemoore/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 147, "cc_name": "Woodland Community College", "system": "colleague_selfservice",
   "base_url": "https://yc-self-service.yccd.edu", "locations": [],
   "params": {"location_match": "Woodland"},
   "source_url": "https://wcc.yccd.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 90, "cc_name": "Yuba College", "system": "colleague_selfservice",
   "base_url": "https://yc-self-service.yccd.edu", "locations": [],
   "params": {"location_match": "Yuba"},
   "source_url": "https://yc.yccd.edu/schedule/",
   "provenance": {"method": "survey", "verified_at": "2026-09-22", "probe_course": "MATH"}},
  {"cc_id": 4, "cc_name": "College of Marin", "system": "marin_colleague",
   "base_url": "https://netapps.marin.edu/Apps/Directory/ScheduleSearch.aspx", "locations": ["0000"],
   "source_url": "https://www1.marin.edu/schedule", "status": "unsupported",
   "note": "Survey 2026-09-22: ScheduleSearch.aspx returns HTTP 500 on postback. Re-check in Phase 4 revalidation."},
  {"cc_id": 3, "cc_name": "Los Angeles City College", "system": "colleague_selfservice",
   "base_url": "https://mycollege-guest.laccd.edu", "locations": [],
   "source_url": "https://www.lacitycollege.edu/academics/class-schedules", "status": "unsupported",
   "note": "LACCD PeopleSoft behind SSO and Azure WAF; no anonymous adapter possible. System value is a placeholder so the entry validates."}
]
```

Note: `cc_name` values must stay exactly as they appear in the ASSIST database (`select distinct cc_name from articulation_rows`) because `join` and the CLI match on `cc_id`, and the name is display-only; `cc_id` values above come from that table.

- [ ] **Step 2: Run the catalog smoke tests**

Run: `uv run pytest tests/schedule/test_catalog.py -q`
Expected: PASS for every entry (each is parametrized).

- [ ] **Step 3: Verify shared-portal parameters with the discovery script**

Run each of these and compare the printed `locations` list against the entries above:

```bash
uv run python -m scripts.discover_colleague https://selfservice.scccd.edu
uv run python -m scripts.discover_colleague https://selfservice.gcccd.edu
uv run python -m scripts.discover_colleague https://ellucianssui.whccd.edu
uv run python -m scripts.discover_colleague https://yc-self-service.yccd.edu
uv run python -m scripts.discover_colleague https://colss-prod.cloud.rsccd.edu
```

If a portal prints location codes for its colleges, set that college's `locations` to the matching code and delete its `location_match` param. If it prints nothing, keep `location_match`. If `suggested_term_format` disagrees with a `term_format` in the file, the file is wrong: fix it.

- [ ] **Step 4: Live smoke test one college per family**

These hit the network and are not part of the test suite. Run:

```bash
uv run python -m src.schedule.cli query --target-school "University of California, Los Angeles" --target-major "Computer Science" --term "Fall 2026" --cc-name "Mount San Antonio" --requirement "MATH 31A"
uv run python -m src.schedule.cli query --target-school "University of California, Los Angeles" --target-major "Computer Science" --term "Fall 2026" --cc-name "Evergreen Valley" --requirement "MATH 31A"
uv run python -m src.schedule.cli query --target-school "University of California, Los Angeles" --target-major "Computer Science" --term "Fall 2026" --cc-name "Chaffey" --requirement "MATH 31A"
```

Expected: each prints at least one section with non-empty `meetings` (days and times) and a modality other than `unknown` for in-person sections. If a college returns a request error, record it in that entry's `note` and set `"status": "stale"`; do not delete the entry.

- [ ] **Step 5: Update the README supported-colleges table**

In `README.md`, replace the adapter table rows for Mt. SAC, CCSF, Evergreen Valley, and Marin so the family column reads `banner9_ssb` / `colleague_selfservice` / `marin_colleague (unsupported)`, and add one line under the table:

```
Full catalog with per-district parameters: `src/schedule/data/colleges.json` (about 40 colleges as of Phase 1). Entries carry `status` (`active`, `stale`, `unsupported`) and `params` (`term_format`, `campus_codes`, `location_match`).
```

- [ ] **Step 6: Run the full suite and commit**

Run: `uv run pytest -q`
Expected: PASS.

```bash
git add src/schedule/data/colleges.json README.md
git commit -m "feat(catalog): schema v2 entries for 13 Banner 9 and 23 Colleague colleges; fix stale hosts"
```

---

### Task 7: Timezone fit and API exposure

**Files:**
- Create: `src/schedule/fit.py`
- Create: `src/web/serialize.py`
- Modify: `src/web/routers/search.py`
- Test: `tests/schedule/test_fit.py`, `tests/web/test_serialize.py`, `tests/web/test_routes.py`

**Interfaces:**
- Consumes: `Meeting`, `ParsedSection` from Task 1.
- Produces: `fit.classify_fit(section, *, student_utc_offset_minutes, window_start_hour=8, window_end_hour=23) -> str` returning `"async" | "fits" | "conflicts" | "unknown"`; `serialize.section_to_dict(section, *, student_utc_offset_minutes: int | None) -> dict`; `GET /api/search` accepts `utc_offset` (minutes east of UTC, e.g. `480` for UTC+8) and every section dict gains `fit` (string or `null` when no offset given) plus `meetings`, `seats_total`, `seats_used`, `course_code_as_listed`.

Fit rules: a section with no meetings is `unknown`. A section whose meetings are all untimed is `async` if its modality is `async_online` or every meeting is online, else `unknown`. Otherwise convert each timed meeting to the student's local clock using the campus timezone offset on the meeting's start date (or today when the date is missing), and the section `fits` only if every timed meeting starts and ends inside `[window_start_hour, window_end_hour)` on the same student-local day; anything else is `conflicts`.

- [ ] **Step 1: Write the failing fit tests**

Create `tests/schedule/test_fit.py`:

```python
from __future__ import annotations

from datetime import date, time

from src.schedule.fit import classify_fit, to_student_local
from src.schedule.models import Meeting, ParsedSection


def _section(modality="in_person", meetings=()) -> ParsedSection:
    return ParsedSection(section_id="1", status="open", modality=modality, title="T", instructor="",
                         meetings=tuple(meetings))


PDT = date(2026, 8, 24)   # UTC-7
PST = date(2026, 12, 1)   # UTC-8
CHINA = 480               # UTC+8


def test_to_student_local_pdt():
    # 07:30 PDT = 14:30 UTC = 22:30 China
    assert to_student_local(time(7, 30), PDT, "America/Los_Angeles", CHINA) == (time(22, 30), 0)


def test_to_student_local_pst_crosses_midnight():
    # 18:00 PST = 02:00 UTC next day = 10:00 China next day
    assert to_student_local(time(18, 0), PST, "America/Los_Angeles", CHINA) == (time(10, 0), 1)


def test_no_meetings_is_unknown():
    assert classify_fit(_section(), student_utc_offset_minutes=CHINA) == "unknown"


def test_untimed_online_is_async():
    s = _section(modality="async_online", meetings=[Meeting(is_online=True)])
    assert classify_fit(s, student_utc_offset_minutes=CHINA) == "async"


def test_untimed_in_person_is_unknown():
    s = _section(modality="in_person", meetings=[Meeting(location="TBA")])
    assert classify_fit(s, student_utc_offset_minutes=CHINA) == "unknown"


def test_morning_pacific_fits_china_evening():
    # 06:30-08:00 PDT = 21:30-23:00 China, inside the default 08..23 window
    m = Meeting(days=("M",), start_local=time(6, 30), end_local=time(8, 0), start_date=PDT)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA) == "fits"


def test_meeting_ending_past_student_midnight_conflicts():
    # 07:30-09:00 PDT = 22:30-00:00 China; the end crosses midnight, so it conflicts
    m = Meeting(days=("M",), start_local=time(7, 30), end_local=time(9, 0), start_date=PDT)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA) == "conflicts"


def test_afternoon_pacific_conflicts_china_night():
    m = Meeting(days=("M",), start_local=time(14, 0), end_local=time(15, 30), start_date=PDT)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA) == "conflicts"


def test_custom_window():
    m = Meeting(days=("M",), start_local=time(14, 0), end_local=time(15, 30), start_date=PDT)
    # 14:00 PDT = 05:00 China; allow 5..23
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=CHINA,
                        window_start_hour=5, window_end_hour=23) == "fits"


def test_any_conflicting_meeting_conflicts():
    ok = Meeting(days=("M",), start_local=time(6, 30), end_local=time(8, 0), start_date=PDT)
    bad = Meeting(days=("W",), start_local=time(14, 0), end_local=time(15, 0), start_date=PDT)
    assert classify_fit(_section(meetings=[ok, bad]), student_utc_offset_minutes=CHINA) == "conflicts"


def test_pacific_student_fits_by_identity():
    m = Meeting(days=("M",), start_local=time(14, 0), end_local=time(15, 30), start_date=PDT)
    assert classify_fit(_section(meetings=[m]), student_utc_offset_minutes=-420) == "fits"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/schedule/test_fit.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.schedule.fit'`.

- [ ] **Step 3: Implement fit**

Create `src/schedule/fit.py`:

```python
"""Classify whether a section's meeting times work for a student in another timezone."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import Meeting, ParsedSection

FIT_ASYNC = "async"
FIT_FITS = "fits"
FIT_CONFLICTS = "conflicts"
FIT_UNKNOWN = "unknown"


def to_student_local(
    campus_time: time, on_date: date, campus_tz: str, student_utc_offset_minutes: int
) -> tuple[time, int]:
    """Return (student-local time, day shift) for a campus-local clock time on a date."""
    campus_dt = datetime.combine(on_date, campus_time, tzinfo=ZoneInfo(campus_tz))
    student_dt = campus_dt.astimezone(timezone(timedelta(minutes=student_utc_offset_minutes)))
    day_shift = (student_dt.date() - on_date).days
    return student_dt.time().replace(tzinfo=None), day_shift


def _meeting_fits(
    meeting: Meeting, *, student_utc_offset_minutes: int, window_start_hour: int, window_end_hour: int
) -> bool:
    assert meeting.start_local is not None and meeting.end_local is not None
    on_date = meeting.start_date or date.today()
    start, start_shift = to_student_local(meeting.start_local, on_date, meeting.timezone, student_utc_offset_minutes)
    end, end_shift = to_student_local(meeting.end_local, on_date, meeting.timezone, student_utc_offset_minutes)
    if start_shift != end_shift:
        return False
    window_start = time(window_start_hour, 0)
    window_end = time(window_end_hour, 0) if window_end_hour < 24 else time(23, 59, 59)
    return window_start <= start and end <= window_end


def classify_fit(
    section: ParsedSection,
    *,
    student_utc_offset_minutes: int,
    window_start_hour: int = 8,
    window_end_hour: int = 23,
) -> str:
    if not section.meetings:
        return FIT_UNKNOWN
    timed = [m for m in section.meetings if m.is_timed]
    if not timed:
        all_online = all(m.is_online for m in section.meetings)
        return FIT_ASYNC if (section.modality == "async_online" or all_online) else FIT_UNKNOWN
    fits_all = all(
        _meeting_fits(
            m,
            student_utc_offset_minutes=student_utc_offset_minutes,
            window_start_hour=window_start_hour,
            window_end_hour=window_end_hour,
        )
        for m in timed
    )
    return FIT_FITS if fits_all else FIT_CONFLICTS
```

- [ ] **Step 4: Run the fit tests**

Run: `uv run pytest tests/schedule/test_fit.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing serializer and route tests**

Create `tests/web/test_serialize.py`:

```python
from __future__ import annotations

from datetime import date, time

from src.schedule.models import Meeting, ParsedSection
from src.web.serialize import section_to_dict

_SECTION = ParsedSection(
    section_id="21216", status="open", modality="in_person", title="Calc", instructor="N",
    meetings=(Meeting(days=("M", "W"), start_local=time(7, 30), end_local=time(9, 35),
                      location="Bldg 61 2306", start_date=date(2026, 8, 24), end_date=date(2026, 12, 13)),),
    seats_total=40, seats_used=36, course_code_as_listed="MATH 180",
)


def test_section_to_dict_without_offset():
    d = section_to_dict(_SECTION, student_utc_offset_minutes=None)
    assert d["section_id"] == "21216"
    assert d["fit"] is None
    assert d["seats_total"] == 40
    assert d["course_code_as_listed"] == "MATH 180"
    m = d["meetings"][0]
    assert m["days"] == ["M", "W"]
    assert m["start_local"] == "07:30"
    assert m["end_local"] == "09:35"
    assert m["start_date"] == "2026-08-24"
    assert m["timezone"] == "America/Los_Angeles"


def test_section_to_dict_with_offset_adds_fit():
    # 07:30-09:35 PDT is 22:30-00:35 in UTC+8, which crosses midnight
    d = section_to_dict(_SECTION, student_utc_offset_minutes=480)
    assert d["fit"] == "conflicts"
    assert section_to_dict(_SECTION, student_utc_offset_minutes=-420)["fit"] == "fits"


def test_section_to_dict_untimed_meeting_has_null_times():
    s = ParsedSection(section_id="1", status="open", modality="async_online", title="T", instructor="",
                      meetings=(Meeting(is_online=True),))
    d = section_to_dict(s, student_utc_offset_minutes=480)
    assert d["meetings"][0]["start_local"] is None
    assert d["fit"] == "async"
```

Append to `tests/web/test_routes.py` (reuse the existing `client` fixture and the fake-provider pattern the file already uses; if the file has a helper that patches `search._get_service`, follow it):

```python
def test_search_accepts_utc_offset_and_returns_fit(client, monkeypatch):
    from datetime import date, time

    from src.schedule.models import CourseAvailability, Meeting, ParsedSection
    from src.web.routers import search as search_router

    class _Svc:
        def query(self, **kwargs):
            return [CourseAvailability(
                cc_id=2, cc_name="Test CC", term="Fall 2026", course_code="CS 1", offered=True,
                sections=[ParsedSection(
                    section_id="9", status="open", modality="in_person", title="T", instructor="",
                    meetings=(Meeting(days=("M",), start_local=time(6, 30), end_local=time(8, 0),
                                      start_date=date(2026, 8, 24)),))],
                source_url="https://example.edu")]

    monkeypatch.setattr(search_router, "_get_service", lambda: _Svc())
    res = client.get("/api/search", params={"school": "UCLA", "major": "Computer Science",
                                            "term": "Fall 2026", "utc_offset": 480})
    assert res.status_code == 200
    section = res.json()[0]["sections"][0]
    assert section["fit"] == "fits"
    assert section["meetings"][0]["start_local"] == "06:30"


def test_search_without_utc_offset_has_null_fit(client, monkeypatch):
    from src.schedule.models import CourseAvailability, ParsedSection
    from src.web.routers import search as search_router

    class _Svc:
        def query(self, **kwargs):
            return [CourseAvailability(cc_id=2, cc_name="Test CC", term="Fall 2026", course_code="CS 1",
                                       offered=True, sections=[ParsedSection("9", "open", "unknown", "T", "")],
                                       source_url="https://example.edu")]

    monkeypatch.setattr(search_router, "_get_service", lambda: _Svc())
    res = client.get("/api/search", params={"school": "UCLA", "major": "Computer Science", "term": "Fall 2026"})
    assert res.status_code == 200
    assert res.json()[0]["sections"][0]["fit"] is None


def test_search_rejects_absurd_utc_offset(client):
    res = client.get("/api/search", params={"school": "UCLA", "major": "Computer Science",
                                            "term": "Fall 2026", "utc_offset": 5000})
    assert res.status_code == 422
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/web/test_serialize.py tests/web/test_routes.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.web.serialize'` and, for the route tests, missing `fit` keys.

- [ ] **Step 7: Implement the serializer and the route parameter**

Create `src/web/serialize.py`:

```python
"""Convert schedule dataclasses to JSON-ready dicts for the API."""
from __future__ import annotations

from datetime import date, time
from typing import Any

from src.schedule.fit import classify_fit
from src.schedule.models import Meeting, ParsedSection


def _time_str(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _date_str(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def meeting_to_dict(meeting: Meeting) -> dict[str, Any]:
    return {
        "days": list(meeting.days),
        "start_local": _time_str(meeting.start_local),
        "end_local": _time_str(meeting.end_local),
        "timezone": meeting.timezone,
        "location": meeting.location,
        "is_online": meeting.is_online,
        "start_date": _date_str(meeting.start_date),
        "end_date": _date_str(meeting.end_date),
    }


def section_to_dict(section: ParsedSection, *, student_utc_offset_minutes: int | None) -> dict[str, Any]:
    fit = (
        classify_fit(section, student_utc_offset_minutes=student_utc_offset_minutes)
        if student_utc_offset_minutes is not None
        else None
    )
    return {
        "section_id": section.section_id,
        "status": section.status,
        "modality": section.modality,
        "title": section.title,
        "instructor": section.instructor,
        "meetings": [meeting_to_dict(m) for m in section.meetings],
        "seats_total": section.seats_total,
        "seats_used": section.seats_used,
        "course_code_as_listed": section.course_code_as_listed,
        "fit": fit,
    }
```

In `src/web/routers/search.py`:

1. Add `from ..serialize import section_to_dict` to the imports.
2. Add a query parameter to `search(...)` after `requirement`:

```python
    utc_offset: int | None = Query(default=None, ge=-840, le=840,
                                   description="Student UTC offset in minutes, e.g. 480 for UTC+8"),
```

3. Replace the final `return [...]` with:

```python
    return [
        {
            **{k: v for k, v in asdict(r).items() if k != "sections"},
            "sections": [
                section_to_dict(s, student_utc_offset_minutes=utc_offset) for s in r.sections
            ],
        }
        for r in results
    ]
```

- [ ] **Step 8: Run the tests and the full suite**

Run: `uv run pytest tests/web tests/schedule/test_fit.py -q`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/schedule/fit.py src/web/serialize.py src/web/routers/search.py tests/schedule/test_fit.py tests/web/test_serialize.py tests/web/test_routes.py
git commit -m "feat(web): expose meetings and seats, compute timezone fit from utc_offset"
```

---

### Task 8: UI: days, times, seats, modality filter, hours-fit filter

**Files:**
- Modify: `src/web/templates/index.html`
- Modify: `src/web/static/style.css`
- Modify: `README.md` (Results UX notes)

**Interfaces:**
- Consumes: the `/api/search` response shape from Task 7 (`sections[].meetings[]`, `seats_total`, `seats_used`, `fit`).
- Produces: two new controls (`#modality-filter`, `#fit-filter` with `#utc-offset`) and four new section columns.

This task has no unit tests (the template has none today). Verification is manual in the browser plus the existing route tests.

- [ ] **Step 1: Add the controls**

In `src/web/templates/index.html`, directly after the `status-filter` form group, add:

```html
    <div class="form-group">
      <label for="modality-filter">Modality</label>
      <select id="modality-filter">
        <option value="all">Any modality</option>
        <option value="async_online">Online, no set times</option>
        <option value="sync_online">Online, scheduled</option>
        <option value="hybrid">Hybrid</option>
        <option value="in_person">In person</option>
      </select>
    </div>
    <div class="form-group">
      <label for="utc-offset">My UTC offset (minutes)</label>
      <input type="number" id="utc-offset" step="30" min="-840" max="840" />
    </div>
    <div class="form-group">
      <label for="fit-filter">Hours</label>
      <select id="fit-filter">
        <option value="all">Any hours</option>
        <option value="fits_or_async">Fits my hours or async</option>
        <option value="async">Async only</option>
      </select>
    </div>
```

- [ ] **Step 2: Wire the elements and default the offset from the browser**

In the script block, next to `const statusEl = ...`, add:

```js
    const modalityEl = document.getElementById('modality-filter');
    const fitEl = document.getElementById('fit-filter');
    const utcOffsetEl = document.getElementById('utc-offset');
    utcOffsetEl.value = String(-new Date().getTimezoneOffset());
```

Where the search button builds `params`, add after the requirement line:

```js
      if (utcOffsetEl.value.trim() !== '') params += '&utc_offset=' + encodeURIComponent(utcOffsetEl.value.trim());
```

Register re-render on change, next to the existing `statusEl.addEventListener('change', ...)`:

```js
    modalityEl.addEventListener('change', function() { renderResults(lastResults); });
    fitEl.addEventListener('change', function() { renderResults(lastResults); });
```

- [ ] **Step 3: Filter courses by section modality and fit**

Add these helpers above `renderResults`:

```js
    function sectionPassesFilters(s) {
      if (modalityEl.value !== 'all' && s.modality !== modalityEl.value) return false;
      if (fitEl.value === 'async' && s.fit !== 'async') return false;
      if (fitEl.value === 'fits_or_async' && s.fit !== 'fits' && s.fit !== 'async') return false;
      return true;
    }

    function coursePassesSectionFilters(course) {
      if (modalityEl.value === 'all' && fitEl.value === 'all') return true;
      if (!course.sections || !course.sections.length) return false;
      return course.sections.some(sectionPassesFilters);
    }
```

In `renderResults`, change the filtering loop condition to:

```js
        if ((statusEl.value === 'all' || availabilityKey(item.offered_this_term) === statusEl.value)
            && coursePassesSectionFilters(item)) {
          filtered.push(item);
        }
```

and change the empty-filter message to `'No matches for current filters.'`.

- [ ] **Step 4: Render meeting detail in the sections table**

Replace the `renderSectionsEl` function with:

```js
    function formatMeeting(m) {
      var days = (m.days && m.days.length) ? m.days.join('') : '';
      var when = (m.start_local && m.end_local) ? (m.start_local + '–' + m.end_local) : 'no set time';
      var where = m.is_online ? 'online' : (m.location || '');
      return [days, when, where].filter(Boolean).join(' · ');
    }

    function fitBadgeEl(fit) {
      var span = document.createElement('span');
      span.className = 'badge';
      if (fit === 'fits') { span.classList.add('badge-green'); span.textContent = 'Fits'; }
      else if (fit === 'async') { span.classList.add('badge-blue'); span.textContent = 'Async'; }
      else if (fit === 'conflicts') { span.classList.add('badge-red'); span.textContent = 'Conflicts'; }
      else { span.classList.add('badge-gray'); span.textContent = fit ? 'Unknown' : '—'; }
      return span;
    }

    function renderSectionsEl(sections) {
      if (!sections.length) {
        return document.createTextNode('');
      }
      var visible = sections.filter(sectionPassesFilters);
      var details = document.createElement('details');
      var summary = document.createElement('summary');
      summary.textContent = visible.length + ' of ' + sections.length + ' section(s) match';
      details.appendChild(summary);

      var table = document.createElement('table');
      table.className = 'sections-table';
      var thead = document.createElement('thead');
      var headRow = document.createElement('tr');
      ['Section', 'Status', 'Modality', 'Meets (campus time)', 'Seats', 'Fit', 'Instructor'].forEach(function(label) {
        var th = document.createElement('th');
        th.textContent = label;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = document.createElement('tbody');
      for (var i = 0; i < visible.length; i++) {
        var s = visible[i];
        var row = document.createElement('tr');
        var meets = (s.meetings || []).map(formatMeeting).join('; ');
        var seats = (s.seats_used != null && s.seats_total != null) ? (s.seats_used + '/' + s.seats_total) : '';
        [s.section_id, s.status, s.modality, meets, seats].forEach(function(value) {
          var td = document.createElement('td');
          td.textContent = value || '';
          row.appendChild(td);
        });
        var fitTd = document.createElement('td');
        fitTd.appendChild(fitBadgeEl(s.fit));
        row.appendChild(fitTd);
        var instrTd = document.createElement('td');
        instrTd.textContent = s.instructor || '';
        row.appendChild(instrTd);
        tbody.appendChild(row);
      }
      table.appendChild(tbody);
      details.appendChild(table);
      return details;
    }
```

- [ ] **Step 5: Add the blue badge style**

In `src/web/static/style.css`, after the `.badge-gray` rule, add:

```css
.badge-blue  { background: #dbeafe; color: #1e40af; }
```

- [ ] **Step 6: Verify in the browser**

Run: `uv run uvicorn src.web.app:app --reload` and open `http://127.0.0.1:8000`. Search UCLA / Computer Science / Fall 2026 with the UTC offset field set to `480`. Confirm:

- The sections table shows days, campus-time ranges, seats, and a Fit badge.
- Choosing "Online, no set times" hides courses with no async sections.
- Choosing "Fits my hours or async" hides courses whose every section conflicts.
- Clearing the offset field and searching again shows "—" in the Fit column.

- [ ] **Step 7: Update README results notes**

Under "Results UX notes" in `README.md` add:

```
- Sections show meeting days, campus-local times, seats used/total, and a Fit badge computed from your UTC offset (minutes east of UTC; the page defaults it from your browser). Fit is `Fits`, `Conflicts`, `Async` (no set times, online), or `Unknown`.
- Modality and Hours filters keep a course when at least one of its sections matches.
```

- [ ] **Step 8: Run the full suite and commit**

Run: `uv run pytest -q`
Expected: PASS.

```bash
git add src/web/templates/index.html src/web/static/style.css README.md
git commit -m "feat(web): show meeting times and seats; add modality and hours-fit filters"
```

---

## Self-review notes

Spec coverage for Phase 1 (section 14, item 1):

| Spec item | Task |
|---|---|
| `Meeting` type, modality enum, seats, code as listed (section 5) | 1 |
| Timezone fit computed at query time, never stored (section 5) | 7 |
| Catalog schema v2 with `params`, `status`, `provenance` (6.1) | 2, 6 |
| Banner 9 adapter with `meetingsFaculty` parsing, campus filter (6.2) | 3 |
| Colleague rename, term codes from portal, keyword and location handling (6.3) | 4 |
| Stale adapters: Mt. SAC and CCSF to Banner 9, Marin and LACC unsupported, SMCCD to Banner 9 (6.4) | 6 |
| `ScheduleService` skips unsupported colleges (11, 12) | 2 |
| UI modality and hours filters, stale/unsupported shown distinctly (11) | 8 (filters); the distinct stale/unsupported badge is deferred to Phase 4 where `status` starts changing |
| Fixture-based tests, no network in the suite (13) | every task; live checks are explicit manual steps |

Deferred on purpose: `provenance` is stored in JSON but not loaded into the dataclass (nothing reads it until Phase 4). `revalidate` and the `stale` UI state belong to Phase 4.
