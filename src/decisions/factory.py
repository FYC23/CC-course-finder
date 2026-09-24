"""Pick the decision backend from DECISION_PROVIDER=jev|llm|none (spec section 8.1).

``none`` (or unset) returns None; every call site then uses its deterministic default.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from src.llm.config import model_from_env

from .jev_provider import JevDecisionProvider
from .llm_provider import LlmDecisionProvider
from .types import DecisionProvider

DECISION_PROVIDER_ENV = "DECISION_PROVIDER"


def decision_provider_from_env(env: Mapping[str, str] | None = None) -> DecisionProvider | None:
    source = os.environ if env is None else env
    name = source.get(DECISION_PROVIDER_ENV, "none").strip().lower() or "none"
    if name == "none":
        return None
    if name == "jev":
        return JevDecisionProvider()
    if name == "llm":
        return LlmDecisionProvider(model_from_env(source))
    raise ValueError(f"{DECISION_PROVIDER_ENV} must be jev, llm, or none; got {name!r}")
