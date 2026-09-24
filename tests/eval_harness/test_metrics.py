from __future__ import annotations

import pytest

from evals.metrics import binary_metrics, calibration, choice_metrics, threshold_sweep

PAIRS = [(0.95, True), (0.85, True), (0.6, False), (0.2, False), (0.1, True)]


def test_binary_metrics():
    metrics = binary_metrics(PAIRS)
    assert (metrics.count, metrics.positives, metrics.accuracy_at_half) == (5, 3, 0.6)
    assert metrics.brier == pytest.approx((0.05**2 + 0.15**2 + 0.6**2 + 0.2**2 + 0.9**2) / 5)


def test_threshold_sweep():
    rows = {row.threshold: row for row in threshold_sweep(PAIRS, thresholds=(0.5, 0.9, 0.99))}
    assert (rows[0.5].accepted, rows[0.5].precision, rows[0.5].recall) == (3, 2 / 3, 2 / 3)
    assert (rows[0.9].accepted, rows[0.9].precision, rows[0.9].recall) == (1, 1.0, 1 / 3)
    assert (rows[0.99].accepted, rows[0.99].precision) == (0, None)


def test_calibration_keeps_non_empty_bins_and_puts_one_in_the_last():
    bins = calibration([(0.05, False), (0.07, True), (1.0, True)], bins=10)
    assert [(b.low, b.count) for b in bins] == [(0.0, 2), (0.9, 1)]
    assert bins[0].observed_rate == 0.5 and bins[1].mean_predicted == 1.0


def test_choice_metrics():
    metrics = choice_metrics([("in_person", "in_person"), ("hybrid", "in_person"), ("async_online", "async_online")])
    assert metrics.count == 3 and metrics.accuracy == pytest.approx(2 / 3)
    assert metrics.confusion[("hybrid", "in_person")] == 1


def test_empty_input_is_an_error():
    with pytest.raises(ValueError):
        binary_metrics([])
