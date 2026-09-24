"""Normalization helpers shared by every schedule adapter.

Adapters translate portal-specific fields into the enums in models.py through
these functions so that the rules live in one place and never guess.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time

from .models import DAY_CODES, Meeting

_DAY_KEY_TO_CODE: Mapping[str, str] = {
    "monday": "M",
    "tuesday": "T",
    "wednesday": "W",
    "thursday": "R",
    "friday": "F",
    "saturday": "S",
    "sunday": "U",
}
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
    return tuple(code for code in DAY_CODES if code in present)


def days_from_indices(indices: Iterable[object]) -> tuple[str, ...]:
    """Colleague-style [1, 3] (0=Sunday) to ('M', 'W'), always in weekday order."""
    present = {_INDEX_TO_CODE[i] for i in indices if isinstance(i, int) and i in _INDEX_TO_CODE}
    return tuple(code for code in DAY_CODES if code in present)


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
    # Hybrid evidence from meetings takes priority over any token-based classification.
    online = [m for m in meetings if m.is_online]
    in_person = [m for m in meetings if not m.is_online]
    if online and in_person:
        return "hybrid"

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
    {"onl", "online", "web", "internet", "distance", "remote", "zoom", "virtual"}
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
    """True when a meeting location names an online venue ('ON LINE', 'ONLINE', 'ZOOM').
    A bare 'on' (as in 'On Campus') does not count; only 'on' directly followed by
    'line' does, matching the portal's split spelling 'ON LINE'."""
    if not isinstance(location, str):
        return False
    words = _WORD_RE.findall(location.lower())
    if any(a == "on" and b == "line" for a, b in zip(words, words[1:])):
        return True
    return bool(frozenset(words) & _ONLINE_LOCATION_WORDS)


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
