from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from src.schedule.errors import SpecInvalid
from src.schedule.generic_replay import GenericReplayProvider
from src.schedule.listing import ListingUnsupported
from src.schedule.models import CollegeScheduleSource
from src.schedule.replay.executor import HostThrottle, ReplayExecutor
from src.schedule.replay.listing import extract_listing
from src.schedule.replay.spec import ListingExtract, ValueRule, load_spec
from src.schedule.term import parse_term_label

from .fakes import FakeSession

_BASE = {
    "cc_id": 999, "cc_name": "Test College", "version": 1, "recorded_at": "2026-09-23",
    "probe": {"course_code": "MATH 1", "term": "Fall 2026"},
    "inputs": {"term": {"format": "{yyyy}{SEASON}", "seasons": {"fall": "70"}}},
    "steps": [{"id": "search", "method": "GET", "url": "https://example.edu/api", "query": {"q": "{course_code}"}}],
    "extract": {"kind": "json", "rows": "$.data[*]", "fields": {"section_id": "$.crn"}},
}
_LISTING = {
    "steps": [{"id": "list", "method": "GET", "url": "https://example.edu/list",
               "query": {"term": "{term}", "subject": "{subject}"}}],
    "extract": {"kind": "json", "rows": "$.courses[*]", "code": "$.code", "title": "$.title",
                "description": "$.about"},
}
_SOURCE = CollegeScheduleSource(cc_id=999, cc_name="Test College", system="replay",
                                base_url="https://example.edu", locations=())


def _spec(tmp_path: Path, raw: dict):
    path = tmp_path / "999.json"
    path.write_text(json.dumps(raw))
    return load_spec(path)


def _provider(spec, session):
    executor = ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=lambda s: None)
    return GenericReplayProvider(executor=executor, specs=MappingProxyType({999: spec}))


def test_spec_without_listing_loads_with_none(tmp_path):
    assert _spec(tmp_path, _BASE).listing is None


def test_listing_loads(tmp_path):
    spec = _spec(tmp_path, {**_BASE, "listing": _LISTING})
    assert [s.id for s in spec.listing.steps] == ["list"]
    assert spec.listing.extract == ListingExtract(
        kind="json", rows="$.courses[*]", code=ValueRule(path="$.code"), title=ValueRule(path="$.title"),
        description=ValueRule(path="$.about"),
    )


def test_listing_schema_rejects_unknown_keys(tmp_path):
    bad = {**_LISTING, "extract": {**_LISTING["extract"], "instructor": "$.x"}}
    with pytest.raises(SpecInvalid, match="listing"):
        _spec(tmp_path, {**_BASE, "listing": bad})


def test_listing_rules_are_checked_at_load(tmp_path):
    bad = {**_LISTING, "extract": {**_LISTING["extract"], "rows": "$.courses"}}
    with pytest.raises(SpecInvalid, match="#listing"):
        _spec(tmp_path, {**_BASE, "listing": bad})


def test_listing_placeholders_are_checked_at_load(tmp_path):
    bad = {**_LISTING, "steps": [{**_LISTING["steps"][0], "query": {"x": "{nope}"}}]}
    with pytest.raises(SpecInvalid, match="nope"):
        _spec(tmp_path, {**_BASE, "listing": bad})


def test_extract_listing_json_dedupes():
    body = json.dumps({"courses": [
        {"code": "MATH-1", "title": "One", "about": "a"}, {"code": "MATH 1", "title": "dup"},
        {"code": "", "title": "blank"}, {"code": "MATH-2", "title": "Two"},
    ]})
    extract = ListingExtract(kind="json", rows="$.courses[*]", code=ValueRule(path="$.code"),
                             title=ValueRule(path="$.title"), description=ValueRule(path="$.about"))
    courses = extract_listing((body,), extract)
    assert [(c.code, c.title, c.description) for c in courses] == [("MATH-1", "One", "a"), ("MATH-2", "Two", "")]


def test_extract_listing_html():
    body = "<ul><li class='c'><b>MATH 1</b><i>One</i></li><li class='c'><b>MATH 2</b><i>Two</i></li></ul>"
    extract = ListingExtract(kind="html", rows="li.c", code=ValueRule(css="b"), title=ValueRule(css="i"))
    assert [c.code for c in extract_listing((body,), extract)] == ["MATH 1", "MATH 2"]


def test_provider_list_subject_runs_listing_steps(tmp_path):
    spec = _spec(tmp_path, {**_BASE, "listing": _LISTING})
    session = FakeSession({"https://example.edu/list": json.dumps({"courses": [{"code": "MATH-1", "title": "One"}]})})
    courses = _provider(spec, session).list_subject(source=_SOURCE, term=parse_term_label("Fall 2026"), subject="math")
    assert [c.code for c in courses] == ["MATH-1"]
    assert session.calls[0]["params"] == {"term": "202670", "subject": "MATH"}


def test_provider_without_listing_is_unsupported(tmp_path):
    spec = _spec(tmp_path, _BASE)
    with pytest.raises(ListingUnsupported, match="cc_id=999"):
        _provider(spec, FakeSession({})).list_subject(source=_SOURCE, term=parse_term_label("Fall 2026"), subject="MATH")
