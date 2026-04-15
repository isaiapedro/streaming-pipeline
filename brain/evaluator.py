"""Threshold evaluator — maps a (signal_type, value) pair to an alarm_level.

blood_pressure payloads contain both systolic and diastolic values, so
`evaluate_message` expands them into two independent readings.
"""

from config.thresholds import SIGNAL_THRESHOLDS

_LEVEL_RANK = {"ok": 0, "warning": 1, "critical": 2}


def _eval_single(signal: str, value: float) -> str:
    thresholds = SIGNAL_THRESHOLDS.get(signal)
    if not thresholds:
        return "ok"

    if "critical_high" in thresholds and value >= thresholds["critical_high"]:
        return "critical"
    if "critical_low" in thresholds and value <= thresholds["critical_low"]:
        return "critical"
    if "warning_high" in thresholds and value >= thresholds["warning_high"]:
        return "warning"
    if "warning_low" in thresholds and value <= thresholds["warning_low"]:
        return "warning"
    return "ok"


def evaluate_message(signal_type: str, value) -> list[tuple[str, float, str]]:
    """Return a list of (signal_type, float_value, alarm_level) tuples.

    blood_pressure expands into two entries (systolic_bp, diastolic_bp).
    """
    if signal_type == "blood_pressure":
        sys_v = float(value["systolic"])
        dia_v = float(value["diastolic"])
        return [
            ("systolic_bp",  sys_v, _eval_single("systolic_bp",  sys_v)),
            ("diastolic_bp", dia_v, _eval_single("diastolic_bp", dia_v)),
        ]
    return [(signal_type, float(value), _eval_single(signal_type, float(value)))]
