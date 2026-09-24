"""Offline stand-ins for requests.Session used by the replay tests."""
from __future__ import annotations

from collections.abc import Iterator

import requests


class FakeResponse:
    def __init__(self, text: str = "", status: int = 200, url: str = "",
                 cookies: dict[str, str] | None = None) -> None:
        self.text = text
        self.status_code = status
        self.url = url
        self.cookies = cookies or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} for {self.url}")


class FakeSession:
    """Routes requests by URL prefix.

    A route value is a body string, a FakeResponse, an Exception instance to raise, or a
    list of those consumed in order (one per call). Every call is appended to ``calls``
    as a dict with method, url, params, data, json and headers. Cookies set on a
    FakeResponse are copied into ``cookies`` so cookie captures can read them.
    """

    def __init__(self, routes: dict[str, object]) -> None:
        self._routes: dict[str, object] = {
            prefix: iter(route) if isinstance(route, list) else route
            for prefix, route in routes.items()
        }
        self.calls: list[dict[str, object]] = []
        self.cookies: dict[str, str] = {}
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, *, params=None, data=None, json=None,
                headers=None, timeout=None) -> FakeResponse:
        self.calls.append({
            "method": method, "url": url, "params": dict(params or {}),
            "data": dict(data or {}), "json": json, "headers": dict(headers or {}),
        })
        for prefix, route in self._routes.items():
            if url.startswith(prefix):
                return self._respond(route, url)
        raise AssertionError(f"FakeSession has no route for {url}")

    def _respond(self, route: object, url: str) -> FakeResponse:
        if isinstance(route, Iterator):
            route = next(route)
        if isinstance(route, Exception):
            raise route
        response = route if isinstance(route, FakeResponse) else FakeResponse(text=str(route))
        if not response.url:
            response = FakeResponse(text=response.text, status=response.status_code, url=url,
                                    cookies=response.cookies)
        self.cookies = {**self.cookies, **response.cookies}
        response.raise_for_status()
        return response
