"""GenerativeModel backend for Google's Gemini API. The only module that imports ``google.genai``."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .errors import LlmConfigError, LlmUnavailable
from .model import CallRecord, RawCompletion
from .runner import CompletionRunner


def _sdk() -> tuple[Any, Any, Any]:
    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as err:
        raise LlmConfigError("LLM_PROVIDER=gemini needs the SDK: uv sync --extra gemini") from err
    return genai, errors, types


def _default_client() -> Any:
    """Reads GEMINI_API_KEY or GOOGLE_API_KEY from the environment."""
    genai, _, _ = _sdk()
    try:
        return genai.Client()
    except ValueError as err:
        raise LlmConfigError(f"gemini: {err}") from err


class GeminiModel:
    provider = "gemini"

    def __init__(self, model_id: str, *, client: Any | None = None) -> None:
        self.model_id = model_id
        self._client = client if client is not None else _default_client()
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
        _, errors, types = _sdk()
        json_options: dict[str, Any] = (
            {"response_mime_type": "application/json", "response_json_schema": dict(schema)}
            if schema is not None
            else {}
        )
        config = types.GenerateContentConfig(system_instruction=system, **json_options)
        try:
            response = self._client.models.generate_content(
                model=self.model_id, contents=prompt, config=config
            )
        except (errors.APIError, httpx.HTTPError) as err:
            raise LlmUnavailable(f"gemini: {type(err).__name__}: {err}") from err
        usage = response.usage_metadata
        return RawCompletion(
            text=response.text or "",
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
            refused=response.text is None,
        )
