"""Boundary-value tests for the NEWS2 lookup tables (brain/ews_scorer.py)."""

import pytest

from brain.ews_scorer import (
    ALARM_THRESHOLD,
    EMERGENCY_THRESHOLD,
    alarm_level,
    assess_news2,
    compute_news2,
    subscore,
)
from brain.ews_window import PatientEWSState


@pytest.mark.parametrize("value,expected", [
    (8, 3), (9, 1), (11, 1), (12, 0), (20, 0), (21, 2), (24, 2), (25, 3),
])
def test_respiratory_rate_boundaries(value, expected):
    assert subscore("respiratory_rate", value) == expected


@pytest.mark.parametrize("value,expected", [
    (91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0), (100, 0),
])
def test_spo2_scale1_boundaries(value, expected):
    assert subscore("spo2", value, spo2_scale=1) == expected


@pytest.mark.parametrize("value,expected", [
    (83, 3), (84, 2), (85, 2), (86, 1), (87, 1), (88, 0), (92, 0), (100, 0),
])
def test_spo2_scale2_boundaries(value, expected):
    assert subscore("spo2", value, spo2_scale=2) == expected


def test_spo2_scale_selection_diverges_at_90():
    assert subscore("spo2", 90, spo2_scale=1) == 3
    assert subscore("spo2", 90, spo2_scale=2) == 0


def test_spo2_scale_selection_is_explicit_and_validated():
    with pytest.raises(ValueError, match="spo2_scale"):
        subscore("spo2", 90, spo2_scale=3)


@pytest.mark.parametrize("value,expected", [
    (90, 3), (91, 2), (100, 2), (101, 1), (110, 1), (111, 0), (219, 0), (220, 3),
])
def test_systolic_bp_boundaries(value, expected):
    assert subscore("systolic_bp", value) == expected


@pytest.mark.parametrize("value,expected", [
    (40, 3), (41, 1), (50, 1), (51, 0), (90, 0), (91, 1), (110, 1), (111, 2), (130, 2), (131, 3),
])
def test_heart_rate_boundaries(value, expected):
    assert subscore("heart_rate", value) == expected


@pytest.mark.parametrize("value,expected", [
    (35.0, 3), (35.1, 1), (36.0, 1), (36.1, 0), (38.0, 0), (38.1, 1), (39.0, 1), (39.1, 2),
])
def test_temperature_boundaries(value, expected):
    assert subscore("temperature", value) == expected


def test_compute_news2_aggregates_all_five_signals():
    values = {
        "respiratory_rate": 12,   # 0
        "spo2":              96,  # 0
        "systolic_bp":       130, # 0
        "heart_rate":        75,  # 0
        "temperature":       37.0,  # 0
    }
    assert compute_news2(values) == 0

    deteriorating = {
        "respiratory_rate": 26,   # 3
        "spo2":              90,  # 3 (scale 1)
        "systolic_bp":       85,  # 3
        "heart_rate":        135, # 3
        "temperature":       39.5,  # 2
    }
    assert compute_news2(deteriorating) == 14


def test_compute_news2_missing_signal_raises():
    with pytest.raises(KeyError):
        compute_news2({"heart_rate": 80})


def test_assessment_preserves_single_parameter_escalation():
    values = {
        "respiratory_rate": 8,
        "spo2": 96,
        "systolic_bp": 120,
        "heart_rate": 75,
        "temperature": 37.0,
    }
    assessment = assess_news2(values)
    assert assessment.total_score == 3
    assert assessment.max_parameter_score == 3
    assert alarm_level(assessment.total_score, assessment.max_parameter_score) == "warning"


def test_stale_composite_window_is_not_scored():
    state = PatientEWSState("P-TEST", window_s=60)
    values = {
        "respiratory_rate": 16,
        "spo2": 97,
        "systolic_bp": 120,
        "heart_rate": 75,
        "temperature": 37.0,
    }
    for signal, value in values.items():
        state.update(signal, value, timestamp_ms=1_000)
    assert state.composite_score(now_ms=61_000) == (0, True)
    assert state.composite_score(now_ms=61_001) == (None, False)


@pytest.mark.parametrize("score,expected", [
    (0, "ok"), (4, "ok"), (5, "warning"), (6, "warning"), (7, "critical"), (10, "critical"),
])
def test_alarm_level_thresholds(score, expected):
    assert alarm_level(score) == expected
    assert ALARM_THRESHOLD == 5 and EMERGENCY_THRESHOLD == 7
