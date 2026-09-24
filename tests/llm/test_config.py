from __future__ import annotations

import pytest

from src.llm import anthropic_backend, gemini_backend, openai_backend
from src.llm.anthropic_backend import AnthropicModel
from src.llm.config import model_from_env
from src.llm.errors import LlmConfigError
from src.llm.gemini_backend import GeminiModel
from src.llm.openai_backend import OpenAICompatibleModel


@pytest.fixture(autouse=True)
def no_real_clients(monkeypatch: pytest.MonkeyPatch):
    sentinel = object()
    monkeypatch.setattr(anthropic_backend, "_default_client", lambda: sentinel)
    monkeypatch.setattr(gemini_backend, "_default_client", lambda: sentinel)
    monkeypatch.setattr(openai_backend, "_default_client", lambda base_url: (sentinel, base_url))


@pytest.mark.parametrize("provider, cls", [
    ("anthropic", AnthropicModel), ("gemini", GeminiModel), ("openai", OpenAICompatibleModel),
    (" Anthropic ", AnthropicModel),
])
def test_provider_selects_backend_and_model(provider, cls):
    model = model_from_env({"LLM_PROVIDER": provider, "LLM_MODEL": "some-model"})
    assert isinstance(model, cls) and model.model_id == "some-model"


def test_openai_base_url_is_passed_through():
    model = model_from_env({"LLM_PROVIDER": "openai", "LLM_MODEL": "m", "LLM_BASE_URL": "http://localhost:11434/v1"})
    assert model._client[1] == "http://localhost:11434/v1"


@pytest.mark.parametrize("env, message", [
    ({}, "LLM_PROVIDER is not set"),
    ({"LLM_PROVIDER": "cohere", "LLM_MODEL": "m"}, "LLM_PROVIDER must be one of"),
    ({"LLM_PROVIDER": "anthropic"}, "LLM_MODEL is not set"),
    ({"LLM_PROVIDER": "anthropic", "LLM_MODEL": "  "}, "LLM_MODEL is not set"),
])
def test_bad_configuration_is_a_config_error(env, message):
    with pytest.raises(LlmConfigError, match=message):
        model_from_env(env)
