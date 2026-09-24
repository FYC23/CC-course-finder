"""GenerativeModel backend for OpenAI and OpenAI-compatible hosts (OpenRouter, Ollama, most
cheaper hosted models). The only module that imports ``openai``."""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .errors import LlmConfigError, LlmUnavailable
from .model import CallRecord, RawCompletion
from .runner import CompletionRunner

# Local hosts such as Ollama ignore the key, but the SDK refuses to start without one.
_LOCAL_HOST_KEY = "not-needed"


def _sdk() -> Any:
    try:
        import openai
    except ImportError as err:
        raise LlmConfigError("LLM_PROVIDER=openai needs the SDK: uv sync --extra openai") from err
    return openai


def _default_client(base_url: str | None) -> Any:
    """Reads OPENAI_API_KEY; with LLM_BASE_URL set and no key, sends a placeholder key."""
    openai = _sdk()
    api_key = os.environ.get("OPENAI_API_KEY") or (_LOCAL_HOST_KEY if base_url else None)
    try:
        return openai.OpenAI(api_key=api_key, base_url=base_url)
    except openai.OpenAIError as err:
        raise LlmConfigError(f"openai: {err}") from err


class OpenAICompatibleModel:
    provider = "openai"

    def __init__(
        self, model_id: str, *, base_url: str | None = None, client: Any | None = None
    ) -> None:
        self.model_id = model_id
        self._client = client if client is not None else _default_client(base_url)
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
        openai = _sdk()
        request: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if schema is not None:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": dict(schema), "strict": True},
            }
        try:
            completion = self._client.chat.completions.create(**request)
        except openai.OpenAIError as err:
            raise LlmUnavailable(f"openai: {type(err).__name__}: {err}") from err
        message = completion.choices[0].message
        usage = completion.usage
        return RawCompletion(
            text=message.content or "",
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            refused=bool(getattr(message, "refusal", None)),
        )
