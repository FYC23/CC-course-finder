from __future__ import annotations

from typing import Any

import requests
from requests.exceptions import ReadTimeout

from .config import ASSIST_BASE_URL, USER_AGENT


class AssistHttpClient:
    """Small wrapper around requests with a configurable API base path."""

    def __init__(self, api_prefix: str = "/api", timeout_seconds: int = 30) -> None:
        self.base_url = ASSIST_BASE_URL.rstrip("/")
        self.api_prefix = api_prefix
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Referer": f"{self.base_url}/",
            }
        )
        self._bootstrap_session()

    def get_json(self, path: str, timeout: int | None = None) -> Any:
        url = self._make_url(path)
        self._ensure_xsrf_header()
        response = self.session.get(url, timeout=timeout or self.timeout_seconds)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            if response.status_code == 400:
                self._bootstrap_session()
                self._ensure_xsrf_header()
                retry_response = self.session.get(
                    url, timeout=timeout or self.timeout_seconds
                )
                retry_response.raise_for_status()
                return retry_response.json()
            raise
        return response.json()

    def get_json_with_retry(
        self, path: str, *, timeout: int = 15, max_retries: int = 2
    ) -> Any:
        """Fetch JSON with automatic retry on timeout. Used for unreliable endpoints."""
        for attempt in range(max_retries + 1):
            try:
                return self.get_json(path, timeout=timeout)
            except ReadTimeout:
                if attempt < max_retries:
                    self.session = requests.Session()
                    self.session.headers.update(
                        {
                            "User-Agent": USER_AGENT,
                            "Accept": "application/json",
                            "Referer": f"{self.base_url}/",
                        }
                    )
                    self._bootstrap_session()
                else:
                    raise

    def get_bytes(self, path: str, accept_pdf: bool = False) -> bytes:
        url = self._make_url(path)
        headers = {"Accept": "application/pdf"} if accept_pdf else None
        response = self.session.get(url, timeout=self.timeout_seconds, headers=headers)
        response.raise_for_status()
        return response.content

    def _make_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{normalized}"

    def _bootstrap_session(self) -> None:
        bootstrap_url = f"{self.base_url}/"
        self.session.get(
            bootstrap_url,
            timeout=self.timeout_seconds,
            headers={"Accept": "text/html"},
        )

    def _ensure_xsrf_header(self) -> None:
        token = self.session.cookies.get("X-XSRF-TOKEN")
        if token:
            self.session.headers["X-XSRF-TOKEN"] = token

