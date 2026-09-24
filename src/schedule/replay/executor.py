"""Runs a replay spec's HTTP steps and returns the final step's body (or bodies).

One executor per provider instance, so its response cache lives for one college's
lookups within one search. Requests use fixed timeouts, one retry on a connection
error, and a per-host minimum interval shared across threads.
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

import requests

from ..errors import PortalChanged
from ..term import ParsedTerm
from .captures import evaluate_capture
from .inputs import render
from .spec import ReplaySpec, Step

REQUEST_TIMEOUT_SECONDS = 20
MIN_INTERVAL_PER_HOST = 0.5
RETRY_DELAY_SECONDS = 1.0
USER_AGENT = "Mozilla/5.0 (compatible; cc-course-finder; +https://github.com/FYC23/CC-course-finder)"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    bodies: tuple[str, ...]
    captures: Mapping[str, str]
    final_url: str


class HostThrottle:
    """Keeps at least ``min_interval`` seconds between requests to one host, across threads."""

    def __init__(
        self,
        min_interval: float = MIN_INTERVAL_PER_HOST,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_interval = min_interval
        self._clock = clock
        self._sleeper = sleeper
        self._next_slot: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        with self._lock:
            now = self._clock()
            send_at = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = send_at + self._min_interval
        delay = send_at - now
        if delay > 0:
            self._sleeper(delay)


_SHARED_THROTTLE = HostThrottle()


class ReplayExecutor:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        throttle: HostThrottle | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)
        self._throttle = throttle or _SHARED_THROTTLE
        self._sleeper = sleeper
        self._cache: dict[tuple, Any] = {}

    def execute(self, spec: ReplaySpec, *, term: ParsedTerm, values: Mapping[str, str]) -> ExecutionResult:
        captures: Mapping[str, str] = MappingProxyType({})
        bodies: tuple[str, ...] = ()
        final_url = ""
        for index, step in enumerate(spec.steps):
            scope = MappingProxyType({**values, **captures})
            response = self._request(step, scope)
            captures = MappingProxyType({**captures, **self._captures_of(step, response, term, scope)})
            if index == len(spec.steps) - 1:
                bodies = (response.text, *self._more_pages(step, scope, captures))
                final_url = str(response.url)
        return ExecutionResult(bodies=bodies, captures=captures, final_url=final_url)

    def _captures_of(self, step: Step, response: Any, term: ParsedTerm, scope: Mapping[str, str]) -> dict[str, str]:
        return {
            name: evaluate_capture(
                name=name, capture=capture, step_id=step.id, response_text=response.text,
                cookies=self._session.cookies, term=term, values=scope,
            )
            for name, capture in step.captures.items()
        }

    def _more_pages(self, step: Step, scope: Mapping[str, str], captures: Mapping[str, str]) -> tuple[str, ...]:
        paginate = step.paginate
        if paginate is None:
            return ()
        total_text = captures.get(paginate.total_capture, "")
        total = re.fullmatch(r"\d+", total_text.strip().replace(",", ""), flags=re.ASCII)
        if total is None:
            raise PortalChanged(
                f"step {step.id!r}: pagination total {total_text!r} is not a number"
            )
        needed = math.ceil(int(total.group()) / paginate.page_size)
        if needed > paginate.max_pages:
            logger.warning(
                "step %r: %s results need %d pages; stopping at max_pages=%d, later sections are dropped",
                step.id, total.group(), needed, paginate.max_pages,
            )
        pages = min(needed, paginate.max_pages)
        bodies: list[str] = []
        for page in range(1, pages):
            value = str(paginate.first + page * paginate.increment)
            bodies.append(self._request(step, scope, override={paginate.param: value}).text)
        return tuple(bodies)

    def _request(self, step: Step, scope: Mapping[str, str], *, override: Mapping[str, str] | None = None) -> Any:
        url = render(step.url, scope)
        query = {**{k: render(v, scope) for k, v in step.query.items()}, **(override or {})}
        form = {k: render(v, scope) for k, v in step.form.items()}
        json_body = _render_deep(step.json_body, scope) if step.json_body is not None else None
        headers = {k: render(v, scope) for k, v in step.headers.items()}
        key = (step.method, url, tuple(sorted(query.items())), tuple(sorted(form.items())),
               json.dumps(json_body, sort_keys=True))
        if step.cache and key in self._cache:
            return self._cache[key]
        response = self._send(step.method, url, query=query, form=form, json_body=json_body, headers=headers)
        if urlsplit(str(response.url)).scheme != "https":
            raise PortalChanged(f"step {step.id!r} ended on a non-https URL")
        if step.cache:
            self._cache[key] = response
        return response

    def _send(self, method: str, url: str, *, query: dict, form: dict, json_body: Any, headers: dict) -> Any:
        try:
            return self._send_once(method, url, query=query, form=form, json_body=json_body, headers=headers)
        except requests.ConnectionError:
            self._sleeper(RETRY_DELAY_SECONDS)
            return self._send_once(method, url, query=query, form=form, json_body=json_body, headers=headers)

    def _send_once(self, method: str, url: str, *, query: dict, form: dict, json_body: Any, headers: dict) -> Any:
        self._throttle.wait(url)
        response = self._session.request(
            method, url,
            params=query or None,
            data=form or None,
            json=json_body,
            headers=headers or None,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response


def _render_deep(value: Any, scope: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return render(value, scope)
    if isinstance(value, Mapping):
        return {k: _render_deep(v, scope) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_render_deep(v, scope) for v in value]
    return value
