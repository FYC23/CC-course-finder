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
