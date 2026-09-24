from __future__ import annotations

import pytest

from src.decisions import factory
from src.decisions.jev_provider import JevDecisionProvider
from src.decisions.llm_provider import LlmDecisionProvider
from src.llm.fake import FakeModel


@pytest.mark.parametrize("env", [{}, {"DECISION_PROVIDER": "none"}, {"DECISION_PROVIDER": " NONE "}])
def test_none_or_unset_means_no_provider(env):
    assert factory.decision_provider_from_env(env) is None


def test_llm_builds_from_llm_env(monkeypatch):
    seen: list = []

    def fake_model_from_env(env):
        seen.append(env)
        return FakeModel()

    monkeypatch.setattr(factory, "model_from_env", fake_model_from_env)
    provider = factory.decision_provider_from_env({"DECISION_PROVIDER": "llm", "LLM_PROVIDER": "x"})
    assert isinstance(provider, LlmDecisionProvider)
    assert seen[0]["LLM_PROVIDER"] == "x"


def test_jev_builds_client(monkeypatch):
    monkeypatch.setattr(factory, "JevDecisionProvider", lambda: JevDecisionProvider(client=object()))
    assert isinstance(factory.decision_provider_from_env({"DECISION_PROVIDER": "jev"}), JevDecisionProvider)


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="jev, llm, or none"):
        factory.decision_provider_from_env({"DECISION_PROVIDER": "oracle"})
