from __future__ import annotations

import pytest

from src.schedule.replay.jsonpath import WILDCARD, JsonPathError, first, parse_path, resolve

_DOC = {
    "value": [
        {"id": "1", "meet": [{"day": "M"}, {"day": "W"}], "seats": 42.0},
        {"id": "2", "meet": [], "seats": None},
    ],
    "odd key": {"x": 1},
    "data": None,
}


def test_parse_path_tokens():
    assert parse_path("$") == ()
    assert parse_path("$.value[*].id") == ("value", WILDCARD, "id")
    assert parse_path("$[0]") == (0,)
    assert parse_path("$[-1]") == (-1,)
    assert parse_path('$["odd key"].x') == ("odd key", "x")
    assert parse_path("$['odd key']") == ("odd key",)


@pytest.mark.parametrize("bad", ["value", "$.", "$..x", "$[a]", "$.a[1:2]", "$.a.b["])
def test_parse_path_rejects_unsupported_syntax(bad):
    with pytest.raises(JsonPathError):
        parse_path(bad)


def test_resolve_root_returns_doc():
    assert resolve(_DOC, "$") == [_DOC]


def test_resolve_wildcard_over_list_and_nested():
    assert resolve(_DOC, "$.value[*].id") == ["1", "2"]
    assert resolve(_DOC, "$.value[*].meet[*].day") == ["M", "W"]


def test_resolve_wildcard_over_dict_values():
    assert resolve({"a": {"n": 1}, "b": {"n": 2}}, "$[*].n") == [1, 2]


def test_resolve_index_and_negative_index():
    assert resolve(_DOC, "$.value[1].id") == ["2"]
    assert resolve(_DOC, "$.value[-1].id") == ["2"]
    assert resolve(_DOC, "$.value[5].id") == []


def test_resolve_missing_key_selects_nothing():
    assert resolve(_DOC, "$.nope") == []
    assert resolve(_DOC, "$.value[*].nope") == []


def test_resolve_null_value_is_a_match():
    assert resolve(_DOC, "$.data") == [None]


def test_resolve_quoted_key():
    assert resolve(_DOC, '$["odd key"].x') == [1]


def test_first():
    assert first(_DOC, "$.value[*].id") == "1"
    assert first(_DOC, "$.nope") is None
