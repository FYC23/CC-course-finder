"""FakeModel: canned replies for tests, run through the same CompletionRunner as real backends."""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from .model import CallRecord, RawCompletion
from .runner import CompletionRunner

REFUSAL = object()
"""A canned reply that makes the fake behave like a model that declined to answer."""


class FakeModel:
    """Each canned reply is a dict (sent as JSON), a str (sent verbatim, so tests can send
    malformed JSON), REFUSAL, or an exception instance raised from the send."""

    provider = "fake"

    def __init__(
        self,
        *,
        structured: Iterable[object] = (),
        text: Iterable[object] = (),
        model_id: str = "fake-model",
    ) -> None:
        self.model_id = model_id
        self._structured: Iterator[object] = iter(tuple(structured))
        self._text: Iterator[object] = iter(tuple(text))
        self._runner = CompletionRunner(provider=self.provider, model_id=model_id)
        self._prompts: list[tuple[str, str]] = []

    def complete_structured(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._runner.structured(
            lambda prompt: self._send(self._structured, system, prompt), user=user, schema=schema
        )

    def complete_text(self, *, system: str, user: str) -> str:
        return self._runner.text(lambda prompt: self._send(self._text, system, prompt), user=user)

    def call_records(self) -> tuple[CallRecord, ...]:
        return self._runner.records()

    def prompts(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._prompts)

    def _send(self, replies: Iterator[object], system: str, prompt: str) -> RawCompletion:
        self._prompts.append((system, prompt))
        reply = next(replies, None)
        if reply is None:
            raise AssertionError("FakeModel has no canned reply left")
        if isinstance(reply, BaseException):
            raise reply
        if reply is REFUSAL:
            return RawCompletion(text="", refused=True)
        body = reply if isinstance(reply, str) else json.dumps(reply)
        return RawCompletion(text=body, input_tokens=len(prompt), output_tokens=len(body))
