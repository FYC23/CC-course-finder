"""Replay spec model: frozen dataclasses built from a schema-validated JSON file.

A spec is data recorded from a college's schedule portal: a short list of HTTP steps
plus an extraction block. ``load_spec`` validates the JSON against ``schema.json``,
converts it to dataclasses, then runs a few semantic checks the schema cannot express,
and raises ``SpecInvalid`` naming the file and field on any failure.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

import jsonschema
from jsonschema.exceptions import best_match

from ..errors import SpecInvalid
from .checks import check_semantics

_SCHEMA_PATH = Path(__file__).parent / "schema.json"
_SCHEMA: dict = json.loads(_SCHEMA_PATH.read_text())
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
class ListingExtract:
    kind: str
    rows: str
    code: ValueRule
    title: ValueRule
    marker: str | None = None
    description: ValueRule | None = None


@dataclass(frozen=True)
class ListingSpec:
    """Optional steps that list every course in ``{subject}`` this term (discover pass only)."""

    steps: tuple[Step, ...]
    extract: ListingExtract


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
    listing: ListingSpec | None = None


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
    check_semantics(spec)
    if spec.listing is not None:
        check_semantics(listing_view(spec))
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
        listing=_listing(raw.get("listing")),
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


def _listing(raw: dict | None) -> ListingSpec | None:
    if raw is None:
        return None
    extract = raw["extract"]
    kind = extract["kind"]
    return ListingSpec(
        steps=tuple(_step(s) for s in raw["steps"]),
        extract=ListingExtract(
            kind=kind,
            rows=extract["rows"],
            marker=extract.get("marker"),
            code=value_rule(extract["code"], kind),
            title=value_rule(extract["title"], kind),
            description=_opt_rule(extract, "description", kind),
        ),
    )


def listing_view(spec: ReplaySpec) -> ReplaySpec:
    """The listing's steps and rules as a plain spec, so load-time checks and the executor
    treat them exactly like a search. The field names only route rules to the checks."""
    if spec.listing is None:
        raise ValueError(f"spec cc_id={spec.cc_id} has no listing")
    listing = spec.listing.extract
    fields = {"section_id": listing.code, "title": listing.title}
    if listing.description is not None:
        fields["course_code_as_listed"] = listing.description
    return replace(
        spec,
        steps=spec.listing.steps,
        extract=Extract(kind=listing.kind, rows=listing.rows, marker=listing.marker,
                        fields=MappingProxyType(fields)),
        source_path=f"{spec.source_path}#listing",
        listing=None,
    )
