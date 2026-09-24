"""Shared plumbing for every GenerativeModel backend.

A backend only knows how to send one prompt to its vendor and return a RawCompletion.
CompletionRunner adds what must behave the same everywhere: a timed call record per
attempt, JSON parsing, JSON-schema validation, and exactly one retry when a structured
reply does not match the schema. A refusal is never retried.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from .errors import LlmError, LlmOutputInvalid
from .model import CallRecord, RawCompletion

logger = logging.getLogger(__name__)

Send = Callable[[str], RawCompletion]

RETRY_NOTE = (
    "Your previous reply did not match the required JSON schema ({problem}). "
    "Reply again with only a JSON object that matches the schema."
)


def parse_structured(text: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise LlmOutputInvalid(f"reply is not JSON: {err.msg}") from err
    if not isinstance(data, dict):
        raise LlmOutputInvalid("reply is not a JSON object")
    error = best_match(Draft202012Validator(dict(schema)).iter_errors(data))
    if error is not None:
        raise LlmOutputInvalid(f"{error.json_path}: {error.message}")
    return data


def _accept(completion: RawCompletion, schema: Mapping[str, Any]) -> dict[str, Any]:
    if completion.refused:
        raise LlmOutputInvalid("the model declined to answer")
    return parse_structured(completion.text, schema)


class CompletionRunner:
    def __init__(
        self, *, provider: str, model_id: str, clock: Callable[[], float] = time.perf_counter
    ) -> None:
        self.provider = provider
        self.model_id = model_id
        self._clock = clock
        self._records: list[CallRecord] = []
        self._lock = threading.Lock()

    def structured(self, send: Send, *, user: str, schema: Mapping[str, Any]) -> dict[str, Any]:
        first = self._timed(send, user, operation="structured", attempt=1)
        try:
            return _accept(first, schema)
        except LlmOutputInvalid as err:
            if first.refused:
                raise
            problem = str(err)
        logger.warning(
            "%s/%s structured reply rejected, retrying once: %s", self.provider, self.model_id, problem
        )
        retry_prompt = f"{user}\n\n{RETRY_NOTE.format(problem=problem)}"
        second = self._timed(send, retry_prompt, operation="structured", attempt=2)
        return _accept(second, schema)

    def text(self, send: Send, *, user: str) -> str:
        completion = self._timed(send, user, operation="text", attempt=1)
        if completion.refused:
            raise LlmOutputInvalid("the model declined to answer")
        return completion.text

    def records(self) -> tuple[CallRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def _timed(self, send: Send, prompt: str, *, operation: str, attempt: int) -> RawCompletion:
        started = self._clock()
        try:
            completion = send(prompt)
        except LlmError:
            self._record(operation, attempt, started, None)
            raise
        self._record(operation, attempt, started, completion)
        return completion

    def _record(
        self, operation: str, attempt: int, started: float, completion: RawCompletion | None
    ) -> None:
        record = CallRecord(
            provider=self.provider,
            model_id=self.model_id,
            operation=operation,
            attempt=attempt,
            latency_ms=int((self._clock() - started) * 1000),
            input_tokens=completion.input_tokens if completion else None,
            output_tokens=completion.output_tokens if completion else None,
            ok=completion is not None,
        )
        with self._lock:
            self._records.append(record)
        logger.info(
            "llm call provider=%s model=%s op=%s attempt=%d ok=%s latency_ms=%d in=%s out=%s",
            record.provider, record.model_id, record.operation, record.attempt, record.ok,
            record.latency_ms, record.input_tokens, record.output_tokens,
        )
