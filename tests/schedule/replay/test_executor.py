from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from src.schedule.errors import PortalChanged
from src.schedule.replay.executor import ExecutionResult, HostThrottle, ReplayExecutor
from src.schedule.replay.inputs import build_values
from src.schedule.replay.spec import load_spec
from src.schedule.term import parse_term_label

from .fakes import FakeResponse, FakeSession

_FALL = parse_term_label("Fall 2026")


def _spec(tmp_path: Path, steps: list[dict], inputs: dict | None = None):
    data = {
        "cc_id": 999, "cc_name": "Test", "version": 1, "recorded_at": "2026-09-23",
        "probe": {"course_code": "MATH 1", "term": "Fall 2026"},
        "inputs": inputs if inputs is not None else {
            "term": {"format": "{yy}{SEASON}", "seasons": {"fall": "FAL"}}},
        "steps": steps,
        "extract": {"kind": "json", "rows": "$.rows[*]", "fields": {"section_id": "$.id"}},
    }
    path = tmp_path / "999.json"
    path.write_text(json.dumps(data))
    return load_spec(path)


def _executor(session: FakeSession, sleeper=None) -> ReplayExecutor:
    return ReplayExecutor(session, throttle=HostThrottle(0.0), sleeper=sleeper or (lambda s: None))


def _run(executor: ReplayExecutor, spec) -> ExecutionResult:
    return executor.execute(spec, term=_FALL, values=build_values(spec.inputs, _FALL, "MATH 1"))


def test_single_get_renders_url_query_and_headers(tmp_path):
    spec = _spec(tmp_path, [{
        "id": "search", "method": "GET", "url": "https://example.edu/api/{term}",
        "query": {"subj": "{subject}", "num": "{number}"}, "headers": {"Accept": "application/json"},
    }])
    session = FakeSession({"https://example.edu/api/26FAL": '{"rows": []}'})
    result = _run(_executor(session), spec)
    assert result.bodies == ('{"rows": []}',)
    assert result.final_url == "https://example.edu/api/26FAL"
    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["params"] == {"subj": "MATH", "num": "1"}
    assert call["headers"] == {"Accept": "application/json"}


def test_post_form_and_json_bodies_are_rendered(tmp_path):
    spec = _spec(tmp_path, [{
        "id": "s", "method": "POST", "url": "https://example.edu/api",
        "form": {"term": "{term}"}, "json": {"q": {"keyword": "{subject} {number}"}},
    }])
    session = FakeSession({"https://example.edu/api": "{}"})
    _run(_executor(session), spec)
    assert session.calls[0]["data"] == {"term": "26FAL"}
    assert session.calls[0]["json"] == {"q": {"keyword": "MATH 1"}}


def test_captures_flow_into_later_steps(tmp_path):
    spec = _spec(tmp_path, [
        {"id": "boot", "method": "GET", "url": "https://example.edu/",
         "captures": {"tok": {"regex": 'name="tok" value="([^"]+)"'}, "sid": {"cookie": "SID"}}},
        {"id": "search", "method": "POST", "url": "https://example.edu/api",
         "form": {"tok": "{tok}", "sid": "{sid}"}},
    ])
    session = FakeSession({
        "https://example.edu/api": "{}",
        "https://example.edu/": FakeResponse(text='<input name="tok" value="T1">', cookies={"SID": "S9"}),
    })
    result = _run(_executor(session), spec)
    assert result.captures == {"tok": "T1", "sid": "S9"}
    assert session.calls[1]["data"] == {"tok": "T1", "sid": "S9"}
    assert result.bodies == ("{}",)


def test_cached_step_is_requested_once_per_executor(tmp_path):
    spec = _spec(tmp_path, [
        {"id": "terms", "method": "GET", "url": "https://example.edu/terms.json", "cache": True,
         "captures": {"term": {"json": "$[0].code"}}},
        {"id": "search", "method": "GET", "url": "https://example.edu/{term}/sections.json", "cache": True},
    ], inputs={})
    session = FakeSession({
        "https://example.edu/terms.json": '[{"code": "202610"}]',
        "https://example.edu/202610/sections.json": '{"rows": []}',
    })
    executor = _executor(session)
    _run(executor, spec)
    _run(executor, spec)
    assert [c["url"] for c in session.calls] == [
        "https://example.edu/terms.json", "https://example.edu/202610/sections.json"]


def test_uncached_step_is_requested_every_run(tmp_path):
    spec = _spec(tmp_path, [{"id": "s", "method": "GET", "url": "https://example.edu/api"}])
    session = FakeSession({"https://example.edu/api": "{}"})
    executor = _executor(session)
    _run(executor, spec)
    _run(executor, spec)
    assert len(session.calls) == 2


def test_retries_once_on_connection_error(tmp_path):
    spec = _spec(tmp_path, [{"id": "s", "method": "GET", "url": "https://example.edu/api"}])
    session = FakeSession({"https://example.edu/api": [requests.ConnectionError("reset"), "{}"]})
    slept: list[float] = []
    result = _run(_executor(session, sleeper=slept.append), spec)
    assert result.bodies == ("{}",)
    assert len(session.calls) == 2
    assert slept == [1.0]


def test_second_connection_error_propagates(tmp_path):
    spec = _spec(tmp_path, [{"id": "s", "method": "GET", "url": "https://example.edu/api"}])
    session = FakeSession({"https://example.edu/api": [
        requests.ConnectionError("a"), requests.ConnectionError("b")]})
    with pytest.raises(requests.ConnectionError, match="b"):
        _run(_executor(session), spec)


def test_http_error_propagates_without_retry(tmp_path):
    spec = _spec(tmp_path, [{"id": "s", "method": "GET", "url": "https://example.edu/api"}])
    session = FakeSession({"https://example.edu/api": FakeResponse(text="", status=500)})
    with pytest.raises(requests.HTTPError):
        _run(_executor(session), spec)
    assert len(session.calls) == 1


def _paged_spec(tmp_path, total_text: str, max_pages: int = 10):
    return _spec(tmp_path, [{
        "id": "search", "method": "GET", "url": "https://example.edu/search",
        "query": {"q": "{subject}", "offset": "0"},
        "captures": {"total": {"css": "#total"}},
        "paginate": {"param": "offset", "first": 0, "increment": 1, "page_size": 20,
                     "max_pages": max_pages, "total_capture": "total"},
    }]), f"<div><span id='total'>{total_text}</span></div>"


def test_paginate_requests_ceil_total_over_page_size_pages(tmp_path):
    spec, page = _paged_spec(tmp_path, "45")
    session = FakeSession({"https://example.edu/search": page})
    result = _run(_executor(session), spec)
    assert len(result.bodies) == 3
    assert [c["params"]["offset"] for c in session.calls] == ["0", "1", "2"]


def test_paginate_single_page_when_total_fits(tmp_path):
    spec, page = _paged_spec(tmp_path, "15")
    session = FakeSession({"https://example.edu/search": page})
    result = _run(_executor(session), spec)
    assert len(result.bodies) == 1


def test_paginate_zero_total_is_one_page(tmp_path):
    spec, page = _paged_spec(tmp_path, "0")
    session = FakeSession({"https://example.edu/search": page})
    assert len(_run(_executor(session), spec).bodies) == 1


def test_paginate_is_capped_by_max_pages(tmp_path):
    spec, page = _paged_spec(tmp_path, "1000", max_pages=3)
    session = FakeSession({"https://example.edu/search": page})
    assert len(_run(_executor(session), spec).bodies) == 3


def test_paginate_non_numeric_total_is_portal_changed(tmp_path):
    spec, page = _paged_spec(tmp_path, "many")
    session = FakeSession({"https://example.edu/search": page})
    with pytest.raises(PortalChanged, match="total"):
        _run(_executor(session), spec)


def test_host_throttle_spaces_requests_per_host():
    clock = iter([0.0, 0.1, 0.1, 5.0]).__next__
    slept: list[float] = []
    throttle = HostThrottle(0.5, clock=clock, sleeper=slept.append)
    throttle.wait("https://a.edu/x")           # t=0.0, first request: no sleep
    throttle.wait("https://a.edu/y")           # t=0.1, must wait until 0.5
    throttle.wait("https://b.edu/z")           # t=0.1, other host: no sleep
    throttle.wait("https://a.edu/w")           # t=5.0, long after: no sleep
    assert slept == [pytest.approx(0.4)]


def test_executor_sets_identifying_user_agent():
    session = FakeSession({})
    ReplayExecutor(session, throttle=HostThrottle(0.0))
    assert "cc-course-finder" in session.headers["User-Agent"]
