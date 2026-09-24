"""Cheap title overlap used only to decide which live courses to ask about first."""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset({"a", "an", "and", "for", "in", "of", "the", "through", "to", "with"})


def title_words(title: str) -> frozenset[str]:
    return frozenset(w for w in _WORD_RE.findall(title.lower().replace("&", " and ")) if w not in _STOP_WORDS)


def title_similarity(a: str, b: str) -> float:
    words_a, words_b = title_words(a), title_words(b)
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)
