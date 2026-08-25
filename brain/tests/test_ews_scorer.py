"""Boundary-value tests for the NEWS2 lookup tables (brain/ews_scorer.py)."""

import pytest

from brain.ews_scorer import subscore, compute_news2, alarm_level, ALARM_THRESHOLD, EMERGENCY_THRESHOLD


@pytest.mark.parametrize("value,expected", [
    (8, 3), (9, 1), (11, 1), (12, 0), (20, 0), (21, 2), (24, 2), (25, 3),
])
def test_respiratory_rate_boundaries(value, expected):
    assert subscore("respiratory_rate", value) == expected


@pytest.mark.parametrize("value,expected", [
    (91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0), (100, 0),
])
def test_spo2_scale1_boundaries(value, expected):
    assert subscore("spo2", value, copd_flag=False) == expected


@pytest.mark.parametrize("value,expected", [
    (83, 3), (84, 2), (85, 2), (86, 1), (87, 1), (88, 0), (92, 0), (100, 0),
])
def test_spo2_scale2_boundaries(value, expected):
    assert subscore("spo2", value, copd_flag=True) == expected


def test_spo2_scale_selection_diverges_at_90():
    # SpO2=90 is the case plan-detailed.md flags: Scale 1 scores it 3 (false
    # alarm territory for a COPD patient); Scale 2 correctly scores it 0.
    assert subscore("spo2", 90, copd_flag=False) == 3
    assert subscore("spo2", 90, copd_flag=True) == 0


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


@pytest.mark.parametrize("score,expected", [
    (0, "ok"), (4, "ok"), (5, "warning"), (6, "warning"), (7, "critical"), (10, "critical"),
])
def test_alarm_level_thresholds(score, expected):
    assert alarm_level(score) == expected
    assert ALARM_THRESHOLD == 5 and EMERGENCY_THRESHOLD == 7
