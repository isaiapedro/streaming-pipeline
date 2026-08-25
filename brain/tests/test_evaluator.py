"""Boundary-value tests for the per-signal threshold evaluator (Approach A,
brain/evaluator.py) — thresholds sourced from config/thresholds.py.
"""

import pytest

from brain.evaluator import evaluate_message


@pytest.mark.parametrize("value,expected", [
    (39, "critical"), (40, "critical"), (45, "warning"), (50, "warning"),
    (75, "ok"), (99, "ok"), (100, "warning"), (119, "warning"), (120, "critical"), (150, "critical"),
])
def test_heart_rate_boundaries(value, expected):
    [(sig, val, level)] = evaluate_message("heart_rate", value)
    assert sig == "heart_rate" and val == float(value) and level == expected


@pytest.mark.parametrize("value,expected", [
    (85, "critical"), (90, "critical"), (91, "warning"), (93, "warning"),
    (94, "warning"), (95, "ok"), (100, "ok"),
])
def test_spo2_boundaries(value, expected):
    [(_sig, _val, level)] = evaluate_message("spo2", value)
    assert level == expected


@pytest.mark.parametrize("value,expected", [
    (85, "warning"), (89, "warning"), (90, "warning"), (91, "ok"),
    (139, "ok"), (140, "warning"), (179, "warning"), (180, "critical"), (200, "critical"),
])
def test_systolic_bp_boundaries(value, expected):
    [(sig, val, level)] = evaluate_message("systolic_bp", value)
    assert sig == "systolic_bp" and level == expected


@pytest.mark.parametrize("value,expected", [
    (5, "warning"), (9, "warning"), (10, "warning"), (11, "ok"),
    (19, "ok"), (20, "warning"), (29, "warning"), (30, "critical"), (35, "critical"),
])
def test_respiratory_rate_boundaries(value, expected):
    [(_sig, _val, level)] = evaluate_message("respiratory_rate", value)
    assert level == expected


@pytest.mark.parametrize("value,expected", [
    (35.0, "warning"), (35.9, "warning"), (36.0, "warning"), (36.1, "ok"),
    (37.4, "ok"), (37.5, "warning"), (38.4, "warning"), (38.5, "critical"), (39.0, "critical"),
])
def test_temperature_boundaries(value, expected):
    [(_sig, _val, level)] = evaluate_message("temperature", value)
    assert level == expected


def test_blood_pressure_expands_into_systolic_and_diastolic():
    readings = evaluate_message("blood_pressure", {"systolic": 190, "diastolic": 70})
    assert readings == [
        ("systolic_bp", 190.0, "critical"),
        ("diastolic_bp", 70.0, "ok"),  # diastolic_bp has no threshold entry at all -> always "ok"
    ]


def test_unknown_signal_falls_back_to_ok():
    [(sig, val, level)] = evaluate_message("unknown_signal", 999)
    assert sig == "unknown_signal" and val == 999.0 and level == "ok"
