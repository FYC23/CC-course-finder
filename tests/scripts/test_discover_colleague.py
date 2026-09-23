from __future__ import annotations

from unittest.mock import MagicMock

import requests

from scripts.discover_colleague import discover, suggest_term_format


def _resp(json_data=None, text=""):
    r = MagicMock(spec=requests.Response)
    r.status_code = 200
    r.json.return_value = json_data if json_data is not None else {}
    r.text = text
    r.raise_for_status = MagicMock()
    return r


def test_suggest_term_format():
    assert suggest_term_format("2026FA", "Fall 2026") == "{yyyy}{SEASON2}"
    assert suggest_term_format("2026/FA", "Fall 2026") == "{yyyy}/{SEASON2}"
    assert suggest_term_format("2026F", "Fall 2026") == "{yyyy}{SEASON1}"
    assert suggest_term_format("26/FA", "Fall 2026") == "{yy}/{SEASON2}"
    assert suggest_term_format("FA26", "Fall 2026") is None


def test_discover_collects_terms_locations_and_format():
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = _resp(text='<input name="__RequestVerificationToken" value="tok">')
    session.post.return_value = _resp({
        "TermFilters": [{"Value": "2026FA", "Description": "Fall 2026 Regular"}],
        "LocationFilters": [{"Value": "EVC", "Description": "Evergreen Valley College"},
                            {"Value": "SJCC", "Description": "San Jose City College"}],
    })
    out = discover("https://selfservice.sjeccd.edu", session)
    assert out["terms"] == [{"value": "2026FA", "description": "Fall 2026 Regular"}]
    assert [loc["value"] for loc in out["locations"]] == ["EVC", "SJCC"]
    assert out["suggested_term_format"] == "{yyyy}{SEASON2}"
    assert session.headers["__RequestVerificationToken"] == "tok"


def test_discover_handles_missing_filters():
    session = MagicMock(spec=requests.Session)
    session.headers = {}
    session.get.return_value = _resp(text="")
    session.post.return_value = _resp({})
    out = discover("https://example.edu", session)
    assert out["terms"] == []
    assert out["locations"] == []
    assert out["suggested_term_format"] is None
