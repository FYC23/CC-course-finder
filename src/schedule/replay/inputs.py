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

_COURSE_CODE_RE = re.compile(r"^\s*([A-Za-z]+)\s*[- ]?\s*([A-Za-z]*\d[A-Za-z0-9]*)\s*$")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingPlaceholder(KeyError):
    """A template names a placeholder that has no value (a spec bug; caught at load)."""


def course_parts(course_code: str) -> tuple[str, str]:
    """('MATH', '150AC') for 'MATH 150AC'. Unparseable codes become (code upper, '')."""
    match = _COURSE_CODE_RE.match(course_code)
    if match is None:
        return course_code.strip().upper(), ""
    return match.group(1).upper(), match.group(2).upper()


def _as_is(source_value: str) -> str:
    return source_value


def _upper(source_value: str) -> str:
    return source_value.upper()


def _dash_join(source_value: str) -> str:
    subject, number = course_parts(source_value)
    return f"{subject}-{number}" if number else subject


def _compact(source_value: str) -> str:
    subject, number = course_parts(source_value)
    return f"{subject}{number}"


_TRANSFORMS: Mapping[str, Callable[[str], str]] = MappingProxyType(
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
        values[name] = _TRANSFORMS[named.transform](source_value)
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
