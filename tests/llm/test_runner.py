from __future__ import annotations

import pytest

from src.llm.errors import LlmOutputInvalid, LlmUnavailable
from src.llm.fake import REFUSAL, FakeModel
from src.llm.model import RawCompletion
from src.llm.runner import CompletionRunner, parse_structured

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def test_valid_reply_is_returned_and_recorded() -> None:
    model = FakeModel(structured=[{"answer": "yes"}])
    assert model.complete_structured(system="s", user="u", schema=SCHEMA) == {"answer": "yes"}
    (record,) = model.call_records()
    assert (record.provider, record.model_id, record.operation, record.attempt, record.ok) == (
        "fake", "fake-model", "structured", 1, True,
    )
    assert record.latency_ms >= 0


def test_schema_mismatch_is_retried_once_with_the_problem() -> None:
    model = FakeModel(structured=[{"answer": 3}, {"answer": "no"}])
    assert model.complete_structured(system="s", user="u", schema=SCHEMA) == {"answer": "no"}
    prompts = [prompt for _, prompt in model.prompts()]
    assert prompts[0] == "u"
    assert prompts[1].startswith("u\n\nYour previous reply did not match the required JSON schema")
    assert "$.answer" in prompts[1]
    assert [r.attempt for r in model.call_records()] == [1, 2]


def test_malformed_json_is_retried() -> None:
    model = FakeModel(structured=["not json", {"answer": "ok"}])
    assert model.complete_structured(system="s", user="u", schema=SCHEMA) == {"answer": "ok"}


def test_second_mismatch_raises_output_invalid() -> None:
    model = FakeModel(structured=["not json", {"wrong": 1}])
    with pytest.raises(LlmOutputInvalid):
        model.complete_structured(system="s", user="u", schema=SCHEMA)
    assert len(model.call_records()) == 2


def test_refusal_is_not_retried() -> None:
    model = FakeModel(structured=[REFUSAL])
    with pytest.raises(LlmOutputInvalid, match="declined"):
        model.complete_structured(system="s", user="u", schema=SCHEMA)
    assert len(model.call_records()) == 1


def test_unavailable_propagates_and_is_recorded_as_failed() -> None:
    model = FakeModel(structured=[LlmUnavailable("down")])
    with pytest.raises(LlmUnavailable):
        model.complete_structured(system="s", user="u", schema=SCHEMA)
    (record,) = model.call_records()
    assert record.ok is False and record.input_tokens is None


def test_text_completion_passes_through() -> None:
    assert FakeModel(text=["hello"]).complete_text(system="s", user="u") == "hello"


def test_text_refusal_raises() -> None:
    with pytest.raises(LlmOutputInvalid, match="declined"):
        FakeModel(text=[REFUSAL]).complete_text(system="s", user="u")


def test_parse_structured_rejects_non_object_json() -> None:
    with pytest.raises(LlmOutputInvalid, match="not a JSON object"):
        parse_structured("[1, 2]", SCHEMA)


def test_runner_latency_and_tokens_come_from_clock_and_completion() -> None:
    ticks = iter([1.0, 1.25])
    runner = CompletionRunner(provider="p", model_id="m", clock=lambda: next(ticks))
    runner.text(lambda prompt: RawCompletion(text="x", input_tokens=5, output_tokens=2), user="u")
    (record,) = runner.records()
    assert (record.latency_ms, record.input_tokens, record.output_tokens) == (250, 5, 2)


def test_fake_model_runs_out_loudly() -> None:
    with pytest.raises(AssertionError, match="no canned reply"):
        FakeModel().complete_text(system="s", user="u")
