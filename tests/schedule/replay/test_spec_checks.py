"""Load-time checks that must catch spec mistakes before Phase 4 generates specs.

Each case below used to load cleanly and only fail (or silently misbehave) at lookup time.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.schedule.errors import SpecInvalid
from src.schedule.replay.spec import load_spec

from .test_spec import MINIMAL, _variant, _write

_HTML_EXTRACT = {"kind": "html", "rows": "article", "fields": {"section_id": "h3"}}


def _load(tmp_path: Path, **changes) -> None:
    load_spec(_write(tmp_path, _variant(**changes)))


def _json_extract(**changes) -> dict:
    extract = copy.deepcopy(MINIMAL["extract"])
    extract.update(changes)
    return extract


def _step(**changes) -> dict:
    step = {"id": "search", "method": "GET", "url": "https://example.edu/api"}
    step.update(changes)
    return step


# --- patterns, paths and selectors compile at load ------------------------------------


def test_bad_value_rule_regex_rejected(tmp_path: Path):
    extract = _json_extract(fields={"section_id": {"path": "$.crn", "regex": "(unclosed"}})
    with pytest.raises(SpecInvalid, match=r"extract\.fields\.section_id.*regex"):
        _load(tmp_path, extract=extract)


def test_bad_regex_inside_join_names_the_part(tmp_path: Path):
    title = {"join": ["$.a", {"path": "$.b", "regex": "[z-a]"}]}
    extract = _json_extract(fields={"section_id": "$.crn", "title": title})
    with pytest.raises(SpecInvalid, match=r"extract\.fields\.title\.join\[1\]"):
        _load(tmp_path, extract=extract)


def test_bad_time_pattern_rejected(tmp_path: Path):
    meeting = {"time_text": "$.when", "time_pattern": "(?P<start>"}
    with pytest.raises(SpecInvalid, match=r"extract\.meetings\[0\]\.time_pattern"):
        _load(tmp_path, extract=_json_extract(meetings=[meeting]))


def test_time_pattern_without_known_groups_rejected(tmp_path: Path):
    meeting = {"time_text": "$.when", "time_pattern": r"(\d+):(\d+)"}
    with pytest.raises(SpecInvalid, match="days, start or end"):
        _load(tmp_path, extract=_json_extract(meetings=[meeting]))


def test_bad_regex_capture_rejected_after_placeholders(tmp_path: Path):
    steps = [
        _step(id="boot", captures={"tok": {"regex": "value=\"([^\"]+)\" {term_label}("}}),
        _step(query={"t": "{tok}"}),
    ]
    with pytest.raises(SpecInvalid, match=r"step 'boot'.*capture 'tok'"):
        _load(tmp_path, steps=steps, inputs={})


def test_regex_capture_with_placeholder_and_quantifier_loads(tmp_path: Path):
    steps = [_step(captures={"code": {"regex": "for=\"(\\d{4})\">\\s*{term_label}"}})]
    _load(tmp_path, steps=steps, inputs={})


def test_bad_json_value_rule_path_rejected(tmp_path: Path):
    extract = _json_extract(fields={"section_id": "$.crn[?(@.x)]"})
    with pytest.raises(SpecInvalid, match=r"extract\.fields\.section_id"):
        _load(tmp_path, extract=extract)


def test_bad_rows_path_rejected(tmp_path: Path):
    with pytest.raises(SpecInvalid, match=r"extract\.rows"):
        _load(tmp_path, extract=_json_extract(rows="data[*]"))


def test_bad_meeting_each_path_rejected(tmp_path: Path):
    meeting = {"each": "$..meetings[*]", "location": "$.room"}
    with pytest.raises(SpecInvalid, match=r"extract\.meetings\[0\]\.each"):
        _load(tmp_path, extract=_json_extract(meetings=[meeting]))


def test_bad_json_capture_path_rejected(tmp_path: Path):
    steps = [_step(captures={"total": {"json": "$.meta..total"}})]
    with pytest.raises(SpecInvalid, match=r"capture 'total'"):
        _load(tmp_path, steps=steps)


def test_bad_lookup_capture_label_rejected(tmp_path: Path):
    lookup = {"rows": "$.terms[*]", "label": "name", "value": "$.code"}
    steps = [_step(id="terms", captures={"term": {"lookup": lookup}}), _step(query={"t": "{term}"})]
    with pytest.raises(SpecInvalid, match=r"capture 'term'.*label"):
        _load(tmp_path, steps=steps, inputs={})


def test_bad_css_selector_rejected(tmp_path: Path):
    extract = {**_HTML_EXTRACT, "fields": {"section_id": "h3[unclosed"}}
    with pytest.raises(SpecInvalid, match=r"extract\.fields\.section_id"):
        _load(tmp_path, extract=extract)


def test_bad_html_rows_and_marker_rejected(tmp_path: Path):
    with pytest.raises(SpecInvalid, match=r"extract\.rows"):
        _load(tmp_path, extract={**_HTML_EXTRACT, "rows": "article >"})
    with pytest.raises(SpecInvalid, match=r"extract\.marker"):
        _load(tmp_path, extract={**_HTML_EXTRACT, "marker": "div..results"})


def test_bad_css_capture_rejected(tmp_path: Path):
    steps = [_step(captures={"total": {"css": "#total >"}})]
    with pytest.raises(SpecInvalid, match=r"capture 'total'"):
        _load(tmp_path, steps=steps)


# --- structure the executor or extractor would silently get wrong ---------------------


def test_duplicate_step_ids_rejected(tmp_path: Path):
    steps = [_step(id="search", cache=True), _step(id="search")]
    with pytest.raises(SpecInvalid, match="duplicate step id 'search'"):
        _load(tmp_path, steps=steps)


def test_attr_on_non_css_capture_rejected(tmp_path: Path):
    steps = [_step(captures={"total": {"json": "$.total", "attr": "value"}})]
    with pytest.raises(SpecInvalid, match=r"capture 'total'.*attr"):
        _load(tmp_path, steps=steps)


def test_attr_on_css_capture_loads(tmp_path: Path):
    steps = [_step(captures={"total": {"css": "#total", "attr": "data-count"}})]
    _load(tmp_path, steps=steps)


def test_attr_on_non_css_value_rule_rejected(tmp_path: Path):
    title = {"join": ["h3", "h4"], "attr": "title"}
    extract = {**_HTML_EXTRACT, "fields": {"section_id": "h3", "title": title}}
    with pytest.raises(SpecInvalid, match=r"extract\.fields\.title.*attr"):
        _load(tmp_path, extract=extract)


def test_named_input_shadowing_builtin_rejected(tmp_path: Path):
    inputs = {"named": {"subject": {"from": "course_code", "transform": "upper"}}}
    with pytest.raises(SpecInvalid, match="inputs.named.subject.*built-in"):
        _load(tmp_path, inputs=inputs, steps=[_step()])


def test_named_input_shadowing_term_input_rejected(tmp_path: Path):
    inputs = copy.deepcopy(MINIMAL["inputs"])
    inputs["named"] = {"term": {"from": "course_code"}}
    with pytest.raises(SpecInvalid, match="inputs.named.term"):
        _load(tmp_path, inputs=inputs)


def test_capture_shadowing_builtin_rejected(tmp_path: Path):
    steps = [_step(captures={"number": {"json": "$.n"}})]
    with pytest.raises(SpecInvalid, match="capture 'number'.*built-in"):
        _load(tmp_path, steps=steps)


def test_capture_shadowing_term_input_rejected(tmp_path: Path):
    steps = [_step(captures={"term": {"json": "$.term"}})]
    with pytest.raises(SpecInvalid, match="capture 'term'"):
        _load(tmp_path, steps=steps)


def test_capture_redefined_by_later_step_rejected(tmp_path: Path):
    steps = [
        _step(id="a", captures={"tok": {"cookie": "t"}}),
        _step(id="b", captures={"tok": {"cookie": "u"}}),
    ]
    with pytest.raises(SpecInvalid, match="capture 'tok'.*step 'a'"):
        _load(tmp_path, steps=steps)


def test_capture_named_term_without_term_input_loads(tmp_path: Path):
    steps = [_step(id="terms", captures={"term": {"json": "$.t"}}), _step(query={"t": "{term}"})]
    _load(tmp_path, steps=steps, inputs={})


def test_placeholder_in_json_body_key_rejected(tmp_path: Path):
    steps = [_step(method="POST", json={"filters": {"{subject}": "x"}})]
    with pytest.raises(SpecInvalid, match="json body key"):
        _load(tmp_path, steps=steps)


def test_placeholder_in_json_body_value_loads(tmp_path: Path):
    steps = [_step(method="POST", json={"filters": [{"subject": "{subject}"}]})]
    _load(tmp_path, steps=steps)


@pytest.mark.parametrize(
    "meeting, message",
    [
        ({"days": {"text": "$.d"}, "time_text": "$.t", "time_pattern": "(?P<start>\\S+)"},
         "days.*time_text"),
        ({"start": "$.s", "time_text": "$.t", "time_pattern": "(?P<start>\\S+)"},
         "start/end.*time_text"),
        ({"time_text": "$.t"}, "time_text needs time_pattern"),
        ({"time_pattern": "(?P<start>\\S+)", "location": "$.room"}, "time_pattern needs time_text"),
    ],
)
def test_meeting_rules_the_extractor_would_drop_rejected(tmp_path: Path, meeting, message):
    with pytest.raises(SpecInvalid, match=message):
        _load(tmp_path, extract=_json_extract(meetings=[meeting]))


def test_json_rows_wildcard_before_the_end_rejected(tmp_path: Path):
    with pytest.raises(SpecInvalid, match=r"extract\.rows.*only the last"):
        _load(tmp_path, extract=_json_extract(rows="$.terms[*].sections[*]"))


@pytest.mark.parametrize("rule", [{"const": "x", "regex": "(x)"}, {"join": ["$.a"], "regex": "(x)"}])
def test_regex_on_const_or_join_rejected(tmp_path: Path, rule):
    extract = _json_extract(fields={"section_id": "$.crn", "title": rule})
    with pytest.raises(SpecInvalid, match=r"extract\.fields\.title.*regex only applies"):
        _load(tmp_path, extract=extract)
