from __future__ import annotations

from types import SimpleNamespace

import anthropic
import httpx
import httpx2
import openai
import pytest
from google.genai import errors as genai_errors

from src.llm.anthropic_backend import AnthropicModel
from src.llm.errors import LlmOutputInvalid, LlmUnavailable
from src.llm.gemini_backend import GeminiModel
from src.llm.openai_backend import OpenAICompatibleModel

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
_REQUEST = httpx2.Request("POST", "https://api.test/v1")


class _Endpoint:
    """Records keyword calls and returns (or raises) canned replies in order."""

    def __init__(self, *replies: object) -> None:
        self._replies = iter(replies)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        reply = next(self._replies)
        if isinstance(reply, BaseException):
            raise reply
        return reply


# --- Anthropic ---------------------------------------------------------------------


def _anthropic_reply(text: str, *, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=12, output_tokens=3),
    )


def _anthropic(*replies):
    endpoint = _Endpoint(*replies)
    client = SimpleNamespace(messages=SimpleNamespace(create=endpoint))
    return AnthropicModel("model-under-test", client=client), endpoint


def test_anthropic_structured_sends_schema_and_parses_reply():
    model, endpoint = _anthropic(_anthropic_reply('{"answer": "yes"}'))
    assert model.complete_structured(system="sys", user="hi", schema=SCHEMA) == {"answer": "yes"}
    call = endpoint.calls[0]
    assert call["model"] == "model-under-test" and call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert call["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    (record,) = model.call_records()
    assert (record.provider, record.input_tokens, record.output_tokens) == ("anthropic", 12, 3)


def test_anthropic_text_sends_no_output_config():
    model, endpoint = _anthropic(_anthropic_reply("plain words"))
    assert model.complete_text(system="sys", user="hi") == "plain words"
    assert "output_config" not in endpoint.calls[0]


def test_anthropic_refusal_is_output_invalid():
    model, _ = _anthropic(_anthropic_reply("", stop_reason="refusal"))
    with pytest.raises(LlmOutputInvalid, match="declined"):
        model.complete_structured(system="s", user="u", schema=SCHEMA)


def test_anthropic_sdk_error_is_unavailable():
    model, _ = _anthropic(anthropic.APIConnectionError(request=_REQUEST))
    with pytest.raises(LlmUnavailable, match="anthropic: APIConnectionError"):
        model.complete_structured(system="s", user="u", schema=SCHEMA)


# --- Gemini ------------------------------------------------------------------------


def _gemini_reply(text):
    return SimpleNamespace(
        text=text, usage_metadata=SimpleNamespace(prompt_token_count=9, candidates_token_count=4)
    )


def _gemini(*replies):
    endpoint = _Endpoint(*replies)
    client = SimpleNamespace(models=SimpleNamespace(generate_content=endpoint))
    return GeminiModel("model-under-test", client=client), endpoint


def test_gemini_structured_sends_json_schema_config():
    model, endpoint = _gemini(_gemini_reply('{"answer": "no"}'))
    assert model.complete_structured(system="sys", user="hi", schema=SCHEMA) == {"answer": "no"}
    call = endpoint.calls[0]
    assert call["model"] == "model-under-test" and call["contents"] == "hi"
    config = call["config"]
    assert config.system_instruction == "sys"
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SCHEMA
    (record,) = model.call_records()
    assert (record.input_tokens, record.output_tokens) == (9, 4)


def test_gemini_text_has_no_json_mime_type():
    model, endpoint = _gemini(_gemini_reply("words"))
    assert model.complete_text(system="sys", user="hi") == "words"
    assert endpoint.calls[0]["config"].response_mime_type is None


def test_gemini_blocked_reply_is_refusal():
    model, _ = _gemini(_gemini_reply(None))
    with pytest.raises(LlmOutputInvalid, match="declined"):
        model.complete_text(system="s", user="u")


@pytest.mark.parametrize("error", [
    genai_errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}),
    httpx.ConnectError("no route"),
])
def test_gemini_errors_are_unavailable(error):
    model, _ = _gemini(error)
    with pytest.raises(LlmUnavailable, match="gemini"):
        model.complete_text(system="s", user="u")


# --- OpenAI-compatible -------------------------------------------------------------


def _openai_reply(content, *, refusal=None, usage=True):
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2) if usage else None,
    )


def _openai(*replies):
    endpoint = _Endpoint(*replies)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=endpoint)))
    return OpenAICompatibleModel("model-under-test", client=client), endpoint


def test_openai_structured_sends_strict_json_schema():
    model, endpoint = _openai(_openai_reply('{"answer": "maybe"}'))
    assert model.complete_structured(system="sys", user="hi", schema=SCHEMA) == {"answer": "maybe"}
    call = endpoint.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "sys"}, {"role": "user", "content": "hi"},
    ]
    assert call["response_format"] == {
        "type": "json_schema", "json_schema": {"name": "answer", "schema": SCHEMA, "strict": True},
    }


def test_openai_missing_usage_records_none():
    model, _ = _openai(_openai_reply("hi", usage=False))
    model.complete_text(system="s", user="u")
    (record,) = model.call_records()
    assert record.input_tokens is None


def test_openai_refusal_is_output_invalid():
    model, _ = _openai(_openai_reply(None, refusal="no"))
    with pytest.raises(LlmOutputInvalid, match="declined"):
        model.complete_text(system="s", user="u")


def test_openai_sdk_error_is_unavailable():
    model, _ = _openai(openai.APIConnectionError(request=_REQUEST))
    with pytest.raises(LlmUnavailable, match="openai: APIConnectionError"):
        model.complete_text(system="s", user="u")
