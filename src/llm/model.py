"""The one interface every generative call in the project goes through.

No module outside src/llm imports a vendor SDK or names a model; callers receive a
GenerativeModel (usually from config.model_from_env) and ask for schema-valid dicts.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RawCompletion:
    """What a backend's single send returns, before parsing."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    refused: bool = False


@dataclass(frozen=True)
class CallRecord:
    """One attempt at one call, for cost and latency comparison across backends."""

    provider: str
    model_id: str
    operation: str  # "structured" | "text"
    attempt: int
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    ok: bool


class GenerativeModel(Protocol):
    provider: str
    model_id: str

    def complete_structured(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Return a dict that validates against ``schema`` or raise an LlmError."""
        ...

    def complete_text(self, *, system: str, user: str) -> str: ...

    def call_records(self) -> tuple[CallRecord, ...]: ...
