from __future__ import annotations

from src.matching.similarity import title_similarity, title_words


def test_words_drop_stop_words_and_punctuation():
    assert title_words("Calculus II: Early Transcendentals") == frozenset({"calculus", "ii", "early", "transcendentals"})
    assert title_words("Reading & Composition") == frozenset({"reading", "composition"})


def test_similarity_ranks_the_right_calculus_higher():
    assert title_similarity("Calculus II", "Calculus II: Early Transcendentals") == 0.5
    assert title_similarity("Calculus II", "Calculus I: Early Transcendentals") == 0.2


def test_empty_titles_score_zero():
    assert title_similarity("", "Calculus") == 0.0
