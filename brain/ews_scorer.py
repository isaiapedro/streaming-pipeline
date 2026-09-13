"""Deterministic NEWS2 (National Early Warning Score 2) composite scorer.

Pure lookup-table logic — no ML, no state. Used by both Approach B (batch)
and Approach C (streaming) as the shared composite scoring function; the
only difference between B and C is *when* this is invoked (see
brain/ews_window.py). Approach A does not use this module at all — it is
the pre-existing per-signal threshold evaluator (brain/evaluator.py).

Dual SpO2 scale support is explicit. Scale 2 is selected only when the
synthetic profile/scenario represents a documented Scale 2 prescription for
confirmed hypercapnic respiratory failure; COPD alone is not sufficient.

All v1 synthetic patients are on room air (no supplemental O2) and always
conscious/alert — both subscores are fixed at 0, per plan-detailed.md scope.
"""

from dataclasses import dataclass


ALARM_THRESHOLD = 5    # NEWS2 >= 5 -> medium risk / urgent review
EMERGENCY_THRESHOLD = 7  # NEWS2 >= 7 -> emergency response
SINGLE_PARAMETER_ESCALATION_SCORE = 3
VALID_SPO2_SCALES = (1, 2)


@dataclass(frozen=True)
class News2Assessment:
    """The scoped room-air/alert NEWS2 result needed for escalation."""

    total_score: int
    max_parameter_score: int


def _bucket(value: float, table: list[tuple[float, float, int]]) -> int:
    """table entries are (low_inclusive, high_inclusive, score); low/high may be +/-inf."""
    for low, high, score in table:
        if low <= value <= high:
            return score
    raise ValueError(f"Value {value} not covered by NEWS2 table")


_RR_TABLE = [
    (float("-inf"), 8,   3),
    (9,             11,  1),
    (12,            20,  0),
    (21,            24,  2),
    (25,            float("inf"), 3),
]

_SPO2_SCALE1_TABLE = [
    (float("-inf"), 91, 3),
    (92,            93, 2),
    (94,            95, 1),
    (96,            float("inf"), 0),
]

# Room-air only (no supplemental O2 in v1) — see module docstring.
_SPO2_SCALE2_TABLE = [
    (float("-inf"), 83, 3),
    (84,            85, 2),
    (86,            87, 1),
    (88,            float("inf"), 0),
]

_SYSBP_TABLE = [
    (float("-inf"), 90,  3),
    (91,            100, 2),
    (101,           110, 1),
    (111,           219, 0),
    (220,           float("inf"), 3),
]

_HR_TABLE = [
    (float("-inf"), 40,  3),
    (41,            50,  1),
    (51,            90,  0),
    (91,            110, 1),
    (111,           130, 2),
    (131,           float("inf"), 3),
]

_TEMP_TABLE = [
    (float("-inf"), 35.0, 3),
    (35.1,          36.0, 1),
    (36.1,          38.0, 0),
    (38.1,          39.0, 1),
    (39.1,          float("inf"), 2),
]

REQUIRED_SIGNALS = ("respiratory_rate", "spo2", "systolic_bp", "heart_rate", "temperature")


def _validate_spo2_scale(spo2_scale: int) -> None:
    if spo2_scale not in VALID_SPO2_SCALES:
        raise ValueError(f"spo2_scale must be 1 or 2, got {spo2_scale!r}")


def subscore(
    signal_type: str,
    value: float,
    spo2_scale: int = 1,
) -> int:
    # NEWS2 bands are defined on clinically-read granularity (whole counts
    # for RR/SpO2/BP/HR, 0.1 degC for temperature) — raw generator output is
    # continuous, so round to that granularity before bucketing. Without
    # this, a value like SpO2=95.37 falls in the gap between the "94-95" and
    # "96+" bucket boundaries and the lookup raises.
    if signal_type == "respiratory_rate":
        return _bucket(round(value), _RR_TABLE)
    if signal_type == "spo2":
        _validate_spo2_scale(spo2_scale)
        scale = spo2_scale
        return _bucket(round(value), _SPO2_SCALE2_TABLE if scale == 2 else _SPO2_SCALE1_TABLE)
    if signal_type == "systolic_bp":
        return _bucket(round(value), _SYSBP_TABLE)
    if signal_type == "heart_rate":
        return _bucket(round(value), _HR_TABLE)
    if signal_type == "temperature":
        return _bucket(round(value, 1), _TEMP_TABLE)
    raise ValueError(f"Unknown NEWS2 signal: {signal_type}")


def assess_news2(values: dict[str, float], spo2_scale: int = 1) -> News2Assessment:
    """Return total and largest parameter scores for escalation decisions."""
    _validate_spo2_scale(spo2_scale)
    scores = [subscore(sig, values[sig], spo2_scale=spo2_scale) for sig in REQUIRED_SIGNALS]
    return News2Assessment(total_score=sum(scores), max_parameter_score=max(scores))


def compute_news2(values: dict[str, float], spo2_scale: int = 1) -> int:
    """Aggregate NEWS2 score from the 5 required signals.

    `values` must contain all of REQUIRED_SIGNALS — supplemental O2 (0) and
    consciousness (0, "alert") are fixed per module docstring and added here.
    Raises KeyError if a required signal is missing — callers must check
    window completeness first (see PatientEWSState.composite_score).
    """
    return assess_news2(values, spo2_scale=spo2_scale).total_score


def alarm_level(news2_score: int, max_parameter_score: int = 0) -> str:
    """Map total and single-parameter scores to project escalation labels."""
    if news2_score >= EMERGENCY_THRESHOLD:
        return "critical"
    if news2_score >= ALARM_THRESHOLD or max_parameter_score >= SINGLE_PARAMETER_ESCALATION_SCORE:
        return "warning"
    return "ok"
