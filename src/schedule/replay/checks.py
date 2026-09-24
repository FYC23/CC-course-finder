"""Load-time checks a replay spec must pass beyond its JSON schema.

``load_spec`` runs ``check_semantics`` after building the dataclasses. Once Phase 4
generates specs, ``cli validate`` is the only gate before a spec reaches students, so every
regex, JSONPath and CSS selector is compiled here, and rule combinations the executor or
extractor would silently ignore are rejected. Each failure raises ``SpecInvalid`` naming
the file and the field.

Spec types are imported for type checking only, because ``spec.py`` imports this module.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from typing import TYPE_CHECKING

import soupsieve

from ..errors import SpecInvalid
from .jsonpath import WILDCARD, JsonPathError, parse_path

if TYPE_CHECKING:
    from .spec import Capture, Extract, MeetingRule, ReplaySpec, Step, ValueRule

BUILTIN_PLACEHOLDERS: frozenset[str] = frozenset(
    {"course_code", "subject", "number", "term_label", "yyyy", "yy", "season", "Season"}
)
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_TIME_GROUPS = frozenset({"days", "start", "end"})
_COMPILE_ERRORS = (re.error, JsonPathError, soupsieve.SelectorSyntaxError)

Compiler = Callable[[str], object]


def check_semantics(spec: ReplaySpec) -> None:
    _check_structure(spec)
    _check_names(spec)
    _check_placeholders(spec)
    _check_rule_kinds(spec)
    _check_meetings(spec)
    _check_extract_patterns(spec)
    _check_capture_patterns(spec)


def _fail(spec: ReplaySpec, where: str, problem: str) -> SpecInvalid:
    return SpecInvalid(f"{spec.source_path}: {where}: {problem}")


def _compiled[T](spec: ReplaySpec, where: str, text: str, compile_: Callable[[str], T]) -> T:
    try:
        return compile_(text)
    except _COMPILE_ERRORS as exc:
        raise _fail(spec, where, f"{text!r} does not compile: {exc}") from exc


def _selector_compiler(spec: ReplaySpec) -> Compiler:
    return parse_path if spec.extract.kind == "json" else soupsieve.compile


# --- steps and names --------------------------------------------------------------------


def _check_structure(spec: ReplaySpec) -> None:
    if spec.extract.kind == "json" and not spec.extract.rows.endswith("[*]"):
        raise _fail(spec, "extract.rows", "must end with [*] for kind=json")
    repeated = [step_id for step_id, n in Counter(s.id for s in spec.steps).items() if n > 1]
    if repeated:
        raise _fail(spec, "steps", f"duplicate step id {repeated[0]!r}")
    for step in spec.steps[:-1]:
        if step.paginate is not None:
            raise _fail(spec, f"step {step.id!r}", "paginate is only allowed on the last step")
    last = spec.steps[-1]
    if last.paginate is not None and last.paginate.total_capture not in last.captures:
        raise _fail(
            spec,
            f"step {last.id!r}",
            f"paginate.total_capture {last.paginate.total_capture!r} is not a capture of this step",
        )


def _shadow_reason(name: str) -> str:
    if name == "term":
        return "shadows the term input (inputs.term)"
    return f"shadows the built-in placeholder {name!r}"


def _check_names(spec: ReplaySpec) -> None:
    """Captures are merged over inputs at run time, so a reused name silently wins."""
    reserved = BUILTIN_PLACEHOLDERS | ({"term"} if spec.inputs.term is not None else set())
    for name in spec.inputs.named:
        if name in reserved:
            raise _fail(spec, f"inputs.named.{name}", _shadow_reason(name))
    defined: Mapping[str, str] = {name: "inputs.named" for name in spec.inputs.named}
    for step in spec.steps:
        for name in step.captures:
            where = f"step {step.id!r}: capture {name!r}"
            if name in reserved:
                raise _fail(spec, where, _shadow_reason(name))
            if name in defined:
                raise _fail(spec, where, f"redefines {name!r} from {defined[name]}")
        defined = {**defined, **{name: f"step {step.id!r}" for name in step.captures}}


# --- placeholders -----------------------------------------------------------------------


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


def _mapping_keys(value: object) -> list[str]:
    if isinstance(value, Mapping):
        return [str(k) for k in value] + [key for v in value.values() for key in _mapping_keys(v)]
    if isinstance(value, (list, tuple)):
        return [key for v in value for key in _mapping_keys(v)]
    return []


def _request_keys(step: Step) -> Iterator[tuple[str, str]]:
    for label, mapping in (("query", step.query), ("form", step.form), ("headers", step.headers)):
        for key in mapping:
            yield label, key
    for key in _mapping_keys(step.json_body or {}):
        yield "json body", key


def _check_placeholders(spec: ReplaySpec) -> None:
    known = BUILTIN_PLACEHOLDERS | set(spec.inputs.named)
    if spec.inputs.term is not None:
        # inputs.build_values renders the term before any named input exists.
        _require_known(spec, spec.inputs.term.format, BUILTIN_PLACEHOLDERS | {"SEASON"}, "inputs.term.format")
        known = known | {"term"}
    for step in spec.steps:
        for label, key in _request_keys(step):
            if _placeholders(key):
                raise _fail(
                    spec, f"step {step.id!r}", f"{label} key {key!r} has a placeholder; only values are rendered"
                )
        for template in _step_templates(step):
            _require_known(spec, template, known, f"step {step.id!r}")
        known = known | set(step.captures)
    for index, rule in enumerate(spec.extract.filters):
        for template in ([rule.equals] if rule.equals is not None else list(rule.any_of)):
            _require_known(spec, template, known, f"extract.filter[{index}]")


def _require_known(spec: ReplaySpec, template: str, known: frozenset[str] | set[str], where: str) -> None:
    unknown = _placeholders(template) - known
    if unknown:
        raise _fail(spec, where, f"unknown placeholder(s) {', '.join(sorted(unknown))}")


# --- value rules ------------------------------------------------------------------------


def _meeting_rules(prefix: str, meeting: MeetingRule) -> Iterator[tuple[str, ValueRule]]:
    for index, flag in enumerate(meeting.day_flags):
        yield f"{prefix}.days.flags[{index}]", flag
    named = (
        ("days.text", meeting.day_text), ("time_text", meeting.time_text),
        ("start", meeting.start), ("end", meeting.end), ("location", meeting.location),
        ("start_date", meeting.start_date), ("end_date", meeting.end_date),
    )
    for name, rule in named:
        if rule is not None:
            yield f"{prefix}.{name}", rule


def _top_rules(extract: Extract) -> Iterator[tuple[str, ValueRule]]:
    for name, rule in extract.fields.items():
        yield f"extract.fields.{name}", rule
    for index, rule in enumerate(extract.filters):
        yield f"extract.filter[{index}].value", rule.value
    if extract.status is not None:
        yield "extract.status", extract.status
    for index, rule in enumerate(extract.modality_tokens):
        yield f"extract.modality.tokens[{index}]", rule
    for index, meeting in enumerate(extract.meetings):
        yield from _meeting_rules(f"extract.meetings[{index}]", meeting)


def _flatten(where: str, rule: ValueRule) -> Iterator[tuple[str, ValueRule]]:
    yield where, rule
    for index, part in enumerate(rule.join):
        yield from _flatten(f"{where}.join[{index}]", part)


def _all_rules(extract: Extract) -> Iterator[tuple[str, ValueRule]]:
    """Every value rule with its field path, join parts included."""
    for where, rule in _top_rules(extract):
        yield from _flatten(where, rule)


def _rule_sources(rule: ValueRule) -> list[str]:
    """Which of path/css/const/join this rule sets. ``const`` counts when it is not
    ``None`` (an empty string is a valid constant, not an absent one); ``join`` counts
    when it is non-empty. ``path``/``css`` stay truthy checks since the schema gives
    both ``minLength: 1``, so an empty string can never reach here for those two."""
    sources = []
    if rule.path:
        sources.append("path")
    if rule.css:
        sources.append("css")
    if rule.const is not None:
        sources.append("const")
    if rule.join:
        sources.append("join")
    return sources


def _check_rule_kinds(spec: ReplaySpec) -> None:
    kind = spec.extract.kind
    for where, rule in _all_rules(spec.extract):
        sources = _rule_sources(rule)
        if len(sources) != 1:
            raise _fail(spec, where, f"value rule needs exactly one of path/css/const/join, got {sources}")
        if kind == "json" and (rule.css or rule.attr):
            raise _fail(spec, where, "css/attr rules are not allowed in a json spec")
        if kind == "html" and rule.path:
            raise _fail(spec, where, "path rules are not allowed in an html spec")
        if rule.attr and not rule.css:
            raise _fail(spec, where, "attr only applies to a css rule")
        if rule.regex is not None and (rule.const is not None or rule.join):
            raise _fail(spec, where, "regex only applies to a path or css rule")
    if kind == "json" and spec.extract.marker:
        raise _fail(spec, "extract.marker", "is only for html specs")


def _check_meetings(spec: ReplaySpec) -> None:
    """Combinations ``extractor._days_and_times`` would silently ignore."""
    for index, meeting in enumerate(spec.extract.meetings):
        where = f"extract.meetings[{index}]"
        has_days = bool(meeting.day_flags) or meeting.day_text is not None
        if meeting.time_text is None:
            if meeting.time_pattern is not None:
                raise _fail(spec, where, "time_pattern needs time_text")
            continue
        if has_days:
            raise _fail(spec, where, "days and time_text cannot be combined; time_text would be ignored")
        if meeting.start is not None or meeting.end is not None:
            raise _fail(spec, where, "start/end and time_text cannot be combined; time_text overrides them")
        if meeting.time_pattern is None:
            raise _fail(spec, where, "time_text needs time_pattern")


# --- patterns, paths and selectors ------------------------------------------------------


def _check_extract_patterns(spec: ReplaySpec) -> None:
    extract = spec.extract
    selector = _selector_compiler(spec)
    _compiled(spec, "extract.rows", extract.rows, selector)
    if extract.kind == "json" and WILDCARD in parse_path(extract.rows)[:-1]:
        raise _fail(
            spec, "extract.rows", "only the last token may be [*] (the extractor reads the first container)"
        )
    if extract.marker:
        _compiled(spec, "extract.marker", extract.marker, soupsieve.compile)
    for index, meeting in enumerate(extract.meetings):
        if meeting.each:
            _compiled(spec, f"extract.meetings[{index}].each", meeting.each, selector)
        if meeting.time_pattern:
            _check_time_pattern(spec, f"extract.meetings[{index}].time_pattern", meeting.time_pattern)
    for where, rule in _all_rules(extract):
        if rule.path:
            _compiled(spec, where, rule.path, parse_path)
        if rule.css:
            _compiled(spec, where, rule.css, soupsieve.compile)
        if rule.regex is not None:
            _compiled(spec, f"{where}.regex", rule.regex, re.compile)


def _check_time_pattern(spec: ReplaySpec, where: str, pattern: str) -> None:
    compiled = _compiled(spec, where, pattern, re.compile)
    if not _TIME_GROUPS & set(compiled.groupindex):
        raise _fail(spec, where, "must name a days, start or end group, e.g. (?P<start>...)")


def _capture_patterns(capture: Capture) -> list[tuple[str, str, Compiler]]:
    if capture.kind == "regex":
        # Placeholders are rendered at run time; any literal stands in for them here.
        return [("regex", _PLACEHOLDER_RE.sub("x", capture.arg), re.compile)]
    if capture.kind == "json":
        return [("json", capture.arg, parse_path)]
    if capture.kind == "css":
        return [("css", capture.arg, soupsieve.compile)]
    if capture.kind == "lookup":
        return [
            ("lookup.rows", capture.arg, parse_path),
            ("lookup.label", capture.lookup_label or "$", parse_path),
            ("lookup.value", capture.lookup_value or "$", parse_path),
        ]
    return []


def _check_capture_patterns(spec: ReplaySpec) -> None:
    for step in spec.steps:
        for name, capture in step.captures.items():
            where = f"step {step.id!r}: capture {name!r}"
            if capture.attr is not None and capture.kind != "css":
                raise _fail(spec, where, "attr only applies to a css capture")
            for label, text, compile_ in _capture_patterns(capture):
                _compiled(spec, f"{where}: {label}", text, compile_)
