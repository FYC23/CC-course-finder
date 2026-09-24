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
from .text import element_text, stringify

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
        texts = [stringify(m) for m in resolve(self._node, rule.path or "$")]
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
        return _apply_regex([element_text(el, rule.attr) for el in elements], rule.regex)

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
        return json_rows(body, extract.rows)
    return html_rows(body, extract.rows, extract.marker)


def json_rows(body: str, rows_path: str) -> list[Row]:
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


def html_rows(body: str, rows_selector: str, marker: str | None) -> list[Row]:
    soup = BeautifulSoup(body, "html.parser")
    if marker and soup.select_one(marker) is None:
        raise PortalChanged(f"page marker {marker!r} not found")
    return [HtmlRow(el) for el in soup.select(rows_selector)]


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
