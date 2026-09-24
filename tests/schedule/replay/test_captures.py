from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from requests.cookies import RequestsCookieJar

from src.schedule.errors import PortalChanged
from src.schedule.replay.captures import evaluate_capture
from src.schedule.replay.spec import Capture
from src.schedule.term import TermNotListedError, parse_term_label

_FALL = parse_term_label("Fall 2026")
_VALUES = {"term_label": "Fall 2026"}


def _eval(capture: Capture, text: str = "", cookies: Mapping | None = None, term=_FALL) -> str:
    return evaluate_capture(
        name="x", capture=capture, step_id="s", response_text=text,
        cookies=cookies or {}, term=term, values=_VALUES,
    )


def test_cookie_capture():
    assert _eval(Capture(kind="cookie", arg="XSRF-TOKEN"), cookies={"XSRF-TOKEN": "abc"}) == "abc"


def test_cookie_missing_is_portal_changed():
    with pytest.raises(PortalChanged, match="cookie"):
        _eval(Capture(kind="cookie", arg="XSRF-TOKEN"), cookies={})


def test_cookie_capture_from_requests_cookie_jar():
    jar = RequestsCookieJar()
    jar.set("XSRF-TOKEN", "abc")
    assert _eval(Capture(kind="cookie", arg="XSRF-TOKEN"), cookies=jar) == "abc"


def test_cookie_conflict_is_portal_changed():
    jar = RequestsCookieJar()
    jar.set("XSRF-TOKEN", "a", domain="a.edu")
    jar.set("XSRF-TOKEN", "b", domain="b.edu")
    with pytest.raises(PortalChanged, match="XSRF-TOKEN"):
        _eval(Capture(kind="cookie", arg="XSRF-TOKEN"), cookies=jar)


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


def test_css_multi_valued_attr_is_space_joined():
    html = "<a class='foo bar'>n</a>"
    assert _eval(Capture(kind="css", arg="a", attr="class"), text=html) == "foo bar"


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
