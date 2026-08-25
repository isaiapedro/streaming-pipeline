"""Inter-signal correlation nudges applied at generation time.

Signals are not statistically independent — clinically, HR/SpO2 move
inversely, RR/SpO2 anti-correlate strongly in COPD, HR/Temp co-rise in
sepsis, and SysBP/HR move inversely under compensatory tachycardia.
Without this, composite EWS scoring fires on unrealistic independent
signal combinations, corrupting FPR measurement (see plan-detailed.md L1).

Correlation is a small additive nudge computed from sibling signals'
latest known values relative to their patient baseline — it does not
replace each generator's own random-walk dynamics.
"""

# Nudge magnitude per unit of triggering-signal deviation from baseline.
_HR_TO_SPO2       = -0.04   # HR up -> SpO2 down
_RR_TO_SPO2_COPD  = -0.10   # RR up -> SpO2 down, stronger in COPD
_RR_TO_SPO2_BASE  = -0.02   # weaker anti-correlation outside COPD
_HR_TO_TEMP       = 0.01    # HR up -> Temp up (sepsis co-rise)
_HR_TO_SYSBP      = -0.15   # HR up -> SysBP down (compensatory tachycardia)


def correlated_delta(
    signal_type: str,
    latest: dict[str, float],
    baselines: dict[str, dict],
    copd_flag: bool = False,
) -> float:
    """Return an additive delta for `signal_type` based on sibling signals.

    `latest` holds the most recent value per signal_type for this patient
    (missing entries — e.g. before the first reading — contribute 0 delta).
    """

    def dev(sig: str) -> float:
        if sig not in latest or sig not in baselines:
            return 0.0
        return latest[sig] - baselines[sig]["mean"]

    if signal_type == "spo2":
        rr_coef = _RR_TO_SPO2_COPD if copd_flag else _RR_TO_SPO2_BASE
        return _HR_TO_SPO2 * dev("heart_rate") + rr_coef * dev("respiratory_rate")

    if signal_type == "temperature":
        return _HR_TO_TEMP * dev("heart_rate")

    if signal_type == "systolic_bp":
        return _HR_TO_SYSBP * dev("heart_rate")

    return 0.0
