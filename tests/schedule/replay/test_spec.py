from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.schedule.errors import SpecInvalid
from src.schedule.replay.registry import load_specs_from
from src.schedule.replay.spec import Capture, Paginate, ValueRule, load_spec, value_rule

MINIMAL = {
    "cc_id": 999,
    "cc_name": "Test College",
    "version": 1,
    "recorded_at": "2026-09-23",
    "probe": {"course_code": "MATH 1", "term": "Fall 2026"},
    "inputs": {"term": {"format": "{yyyy}{SEASON}", "seasons": {"fall": "70"}}},
    "steps": [
        {"id": "search", "method": "GET", "url": "https://example.edu/api",
         "query": {"term": "{term}", "subj": "{subject}"}}
    ],
    "extract": {"kind": "json", "rows": "$.data[*]", "fields": {"section_id": "$.crn"}},
}


def _write(tmp_path: Path, data: dict, name: str = "999.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path


def _variant(**changes) -> dict:
    data = copy.deepcopy(MINIMAL)
    for key, value in changes.items():
        data[key] = value
    return data


def test_load_minimal_spec(tmp_path: Path):
    spec = load_spec(_write(tmp_path, MINIMAL))
    assert spec.cc_id == 999
    assert spec.probe.expect_min_rows == 1
    assert spec.inputs.term is not None and spec.inputs.term.seasons["fall"] == "70"
    assert spec.steps[0].query["term"] == "{term}"
    assert spec.steps[0].cache is False and spec.steps[0].paginate is None
    assert spec.extract.fields["section_id"] == ValueRule(path="$.crn")
    assert spec.source_path.endswith("999.json")


def test_missing_required_key_names_field(tmp_path: Path):
    data = _variant()
    del data["steps"]
    with pytest.raises(SpecInvalid, match="steps"):
        load_spec(_write(tmp_path, data))


def test_unknown_top_level_key_rejected(tmp_path: Path):
    with pytest.raises(SpecInvalid, match="surprise"):
        load_spec(_write(tmp_path, _variant(surprise=1)))


def test_unknown_field_name_rejected(tmp_path: Path):
    extract = {"kind": "json", "rows": "$.d[*]", "fields": {"section_id": "$.a", "colour": "$.b"}}
    with pytest.raises(SpecInvalid, match="colour"):
        load_spec(_write(tmp_path, _variant(extract=extract)))


def test_unreadable_json_is_spec_invalid(tmp_path: Path):
    path = tmp_path / "999.json"
    path.write_text("{not json")
    with pytest.raises(SpecInvalid, match="cannot read"):
        load_spec(path)


def test_unknown_placeholder_rejected(tmp_path: Path):
    steps = [{"id": "s", "method": "GET", "url": "https://example.edu/{mystery}"}]
    with pytest.raises(SpecInvalid, match="mystery"):
        load_spec(_write(tmp_path, _variant(steps=steps)))


def test_capture_from_earlier_step_is_a_known_placeholder(tmp_path: Path):
    steps = [
        {"id": "boot", "method": "GET", "url": "https://example.edu/",
         "captures": {"token": {"regex": "name=\"tok\" value=\"([^\"]+)\""}}},
        {"id": "search", "method": "POST", "url": "https://example.edu/api",
         "form": {"tok": "{token}", "term": "{term}"}},
    ]
    spec = load_spec(_write(tmp_path, _variant(steps=steps)))
    assert spec.steps[0].captures["token"] == Capture(kind="regex", arg='name="tok" value="([^"]+)"')


def test_capture_used_before_defined_rejected(tmp_path: Path):
    steps = [
        {"id": "search", "method": "GET", "url": "https://example.edu/{token}"},
        {"id": "boot", "method": "GET", "url": "https://example.edu/",
         "captures": {"token": {"cookie": "tok"}}},
    ]
    with pytest.raises(SpecInvalid, match="token"):
        load_spec(_write(tmp_path, _variant(steps=steps)))


def test_regex_quantifier_braces_are_not_placeholders(tmp_path: Path):
    steps = [{"id": "s", "method": "GET", "url": "https://example.edu/",
              "captures": {"term": {"regex": "for=\"(\\d{4})\">\\s*{term_label}"}}}]
    spec = load_spec(_write(tmp_path, _variant(steps=steps, inputs={})))
    assert spec.steps[0].captures["term"].arg == 'for="(\\d{4})">\\s*{term_label}'


def test_paginate_only_on_last_step(tmp_path: Path):
    paginate = {"param": "offset", "page_size": 20, "total_capture": "total"}
    steps = [
        {"id": "a", "method": "GET", "url": "https://example.edu/a",
         "captures": {"total": {"css": "#total"}}, "paginate": paginate},
        {"id": "b", "method": "GET", "url": "https://example.edu/b"},
    ]
    with pytest.raises(SpecInvalid, match="last step"):
        load_spec(_write(tmp_path, _variant(steps=steps)))


def test_paginate_total_capture_must_exist(tmp_path: Path):
    steps = [{"id": "a", "method": "GET", "url": "https://example.edu/a",
              "paginate": {"param": "offset", "page_size": 20, "total_capture": "total"}}]
    with pytest.raises(SpecInvalid, match="total"):
        load_spec(_write(tmp_path, _variant(steps=steps)))


def test_paginate_defaults(tmp_path: Path):
    steps = [{"id": "a", "method": "GET", "url": "https://example.edu/a",
              "captures": {"total": {"css": "#total"}},
              "paginate": {"param": "offset", "page_size": 20, "total_capture": "total"}}]
    spec = load_spec(_write(tmp_path, _variant(steps=steps)))
    assert spec.steps[0].paginate == Paginate(
        param="offset", total_capture="total", page_size=20, first=0, increment=1, max_pages=10
    )


def test_json_rows_must_end_with_wildcard(tmp_path: Path):
    extract = {"kind": "json", "rows": "$.data", "fields": {"section_id": "$.crn"}}
    with pytest.raises(SpecInvalid, match=r"\[\*\]"):
        load_spec(_write(tmp_path, _variant(extract=extract)))


def test_css_rule_rejected_in_json_spec(tmp_path: Path):
    extract = {"kind": "json", "rows": "$.d[*]", "fields": {"section_id": {"css": "li"}}}
    with pytest.raises(SpecInvalid, match="css"):
        load_spec(_write(tmp_path, _variant(extract=extract)))


def test_path_rule_rejected_in_html_spec(tmp_path: Path):
    extract = {"kind": "html", "rows": "article", "fields": {"section_id": {"path": "$.x"}}}
    with pytest.raises(SpecInvalid, match="path"):
        load_spec(_write(tmp_path, _variant(extract=extract)))


def test_value_rule_shorthand_depends_on_kind():
    assert value_rule("$.a", "json") == ValueRule(path="$.a")
    assert value_rule("li.x", "html") == ValueRule(css="li.x")
    assert value_rule({"const": "x"}, "json") == ValueRule(const="x")
    joined = value_rule({"join": ["$.a", "$.b"], "sep": "-"}, "json")
    assert joined == ValueRule(join=(ValueRule(path="$.a"), ValueRule(path="$.b")), sep="-")


def test_status_from_seats_and_modality_map_lowercased(tmp_path: Path):
    extract = {
        "kind": "json", "rows": "$.d[*]", "fields": {"section_id": "$.crn"},
        "status": {"from_seats": True},
        "modality": {"tokens": ["$.mode"], "map": {"Partially Online": "hybrid"}},
    }
    spec = load_spec(_write(tmp_path, _variant(extract=extract)))
    assert spec.extract.status is None and spec.extract.status_from_seats is True
    assert spec.extract.modality_map == {"partially online": "hybrid"}


def test_load_specs_from_directory(tmp_path: Path):
    _write(tmp_path, MINIMAL, "999.json")
    _write(tmp_path, _variant(cc_id=998), "998.json")
    specs = load_specs_from(tmp_path)
    assert sorted(specs) == [998, 999]


def test_load_specs_from_rejects_file_name_mismatch(tmp_path: Path):
    _write(tmp_path, MINIMAL, "1.json")
    with pytest.raises(SpecInvalid, match="file name"):
        load_specs_from(tmp_path)


def test_load_specs_from_empty_or_missing_directory_is_empty(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    assert load_specs_from(tmp_path / "empty") == {}
    assert load_specs_from(tmp_path / "missing") == {}


def test_const_empty_string_counts_as_a_source(tmp_path: Path):
    """A schema-valid {"const": ""} must not be rejected as having no source.

    ``_check_rule_kinds`` must count ``const`` as present when ``rule.const is not
    None`` (not a truthiness check, which would treat "" as absent).
    """
    extract = {
        "kind": "json", "rows": "$.d[*]",
        "fields": {"section_id": "$.crn", "title": {"const": ""}},
    }
    spec = load_spec(_write(tmp_path, _variant(extract=extract)))
    assert spec.extract.fields["title"] == ValueRule(const="")


def test_step_url_placeholder_in_host_rejected(tmp_path: Path):
    steps = [{"id": "s", "method": "GET", "url": "https://example.edu{subject}"}]
    with pytest.raises(SpecInvalid, match="url"):
        load_spec(_write(tmp_path, _variant(steps=steps)))


def test_step_url_placeholder_in_path_loads(tmp_path: Path):
    steps = [{"id": "s", "method": "GET", "url": "https://example.edu/{subject}"}]
    spec = load_spec(_write(tmp_path, _variant(steps=steps)))
    assert spec.steps[0].url == "https://example.edu/{subject}"


def test_step_url_with_port_and_no_path_loads(tmp_path: Path):
    steps = [{"id": "s", "method": "GET", "url": "https://example.edu:8443"}]
    assert load_spec(_write(tmp_path, _variant(steps=steps))).steps[0].url == "https://example.edu:8443"


def test_modality_map_value_must_be_a_known_modality(tmp_path: Path):
    extract = {
        "kind": "json", "rows": "$.d[*]", "fields": {"section_id": "$.crn"},
        "modality": {"tokens": ["$.mode"], "map": {"Partially Online": "hybird"}},
    }
    with pytest.raises(SpecInvalid, match="hybird"):
        load_spec(_write(tmp_path, _variant(extract=extract)))
