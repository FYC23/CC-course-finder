"""GenerativeModel backend for Anthropic's Messages API. The only module that imports ``anthropic``.

Structured replies use ``output_config.format`` (JSON-schema constrained output). The
model is whatever LLM_MODEL names; nothing here picks one.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import LlmConfigError, LlmUnavailable
from .model import CallRecord, RawCompletion
from .runner import CompletionRunner

DEFAULT_MAX_TOKENS = 16000


def _sdk() -> Any:
    try:
        import anthropic
    except ImportError as err:
        raise LlmConfigError("LLM_PROVIDER=anthropic needs the SDK: uv sync --extra anthropic") from err
    return anthropic


def _default_client() -> Any:
    """Credentials come from ANTHROPIC_API_KEY (or an `ant auth login` profile)."""
    return _sdk().Anthropic()


class AnthropicModel:
    provider = "anthropic"

    def __init__(
        self, model_id: str, *, client: Any | None = None, max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> None:
        self.model_id = model_id
        self._client = client if client is not None else _default_client()
        self._max_tokens = max_tokens
        self._runner = CompletionRunner(provider=self.provider, model_id=model_id)

    def complete_structured(
        self, *, system: str, user: str, schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._runner.structured(
            lambda prompt: self._send(system, prompt, schema), user=user, schema=schema
        )

    def complete_text(self, *, system: str, user: str) -> str:
        return self._runner.text(lambda prompt: self._send(system, prompt, None), user=user)

    def call_records(self) -> tuple[CallRecord, ...]:
        return self._runner.records()

    def _send(self, system: str, prompt: str, schema: Mapping[str, Any] | None) -> RawCompletion:
        anthropic = _sdk()
        request: dict[str, Any] = {
            "model": self.model_id,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if schema is not None:
            request["output_config"] = {"format": {"type": "json_schema", "schema": dict(schema)}}
        try:
            response = self._client.messages.create(**request)
        except anthropic.AnthropicError as err:
            raise LlmUnavailable(f"anthropic: {type(err).__name__}: {err}") from err
        text = "".join(block.text for block in response.content if block.type == "text")
        return RawCompletion(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            refused=response.stop_reason == "refusal",
        )
