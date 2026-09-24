"""Pick the GenerativeModel from the environment. Nothing else in the project names a
vendor or a model:

    LLM_PROVIDER=anthropic|gemini|openai   LLM_MODEL=<model id>   [LLM_BASE_URL=<openai-compatible host>]
"""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from types import MappingProxyType

from . import anthropic_backend, gemini_backend, openai_backend
from .errors import LlmConfigError
from .model import GenerativeModel

PROVIDER_ENV = "LLM_PROVIDER"
MODEL_ENV = "LLM_MODEL"
BASE_URL_ENV = "LLM_BASE_URL"

_BUILDERS: Mapping[str, Callable[[str, str | None], GenerativeModel]] = MappingProxyType({
    "anthropic": lambda model_id, base_url: anthropic_backend.AnthropicModel(model_id),
    "gemini": lambda model_id, base_url: gemini_backend.GeminiModel(model_id),
    "openai": lambda model_id, base_url: openai_backend.OpenAICompatibleModel(model_id, base_url=base_url),
})
PROVIDERS: tuple[str, ...] = tuple(_BUILDERS)


def model_from_env(env: Mapping[str, str] | None = None) -> GenerativeModel:
    source = os.environ if env is None else env
    provider = source.get(PROVIDER_ENV, "").strip().lower()
    if not provider:
        raise LlmConfigError(f"{PROVIDER_ENV} is not set (one of {', '.join(PROVIDERS)})")
    builder = _BUILDERS.get(provider)
    if builder is None:
        raise LlmConfigError(f"{PROVIDER_ENV} must be one of {', '.join(PROVIDERS)}, got {provider!r}")
    model_id = source.get(MODEL_ENV, "").strip()
    if not model_id:
        raise LlmConfigError(f"{MODEL_ENV} is not set; name the model id for {provider}")
    base_url = source.get(BASE_URL_ENV, "").strip() or None
    return builder(model_id, base_url)
