"""Errors every GenerativeModel backend raises, whatever the vendor."""
from __future__ import annotations


class LlmError(Exception):
    """Base class for generative-model failures."""


class LlmConfigError(LlmError):
    """LLM_PROVIDER or LLM_MODEL is missing or unknown, or the backend's SDK is not installed."""


class LlmUnavailable(LlmError):
    """The provider could not answer: auth, rate limit, network, or a server error."""


class LlmOutputInvalid(LlmError):
    """The model declined, or its structured reply failed the schema twice."""
