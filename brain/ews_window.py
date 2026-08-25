"""Stateful per-patient signal window backing both Approach B and C.

Holds the latest known value per signal for one patient. `composite_score()`
is the shared NEWS2 evaluation point — Approach B calls it on a fixed 60s
tick (batch/periodic assessment), Approach C calls it on every incoming
message (continuous streaming evaluation). Same scoring logic, different
invocation cadence — that cadence difference is exactly what the thesis
compares (see plan-detailed.md L5).

`window_s` bounds how stale a signal's last-known value may be before the
window is considered incomplete — this is the "window completeness" metric:
the % of scoring windows with all 5 signals present and fresh.
"""

from dataclasses import dataclass

from brain.ews_scorer import REQUIRED_SIGNALS, compute_news2


@dataclass
class _Reading:
    value: float
    timestamp_ms: int


class PatientEWSState:
    def __init__(self, patient_id: str, copd_flag: bool = False, window_s: float = 60.0) -> None:
        self.patient_id = patient_id
        self.copd_flag = copd_flag
        self.window_ms = window_s * 1000
        self._latest: dict[str, _Reading] = {}

    def update(self, signal_type: str, value: float, timestamp_ms: int) -> None:
        if signal_type not in REQUIRED_SIGNALS:
            return
        self._latest[signal_type] = _Reading(value=value, timestamp_ms=timestamp_ms)

    def composite_score(self, now_ms: int) -> tuple[int | None, bool]:
        """Return (news2_score, window_complete).

        news2_score is None when one or more required signals have never
        been seen. window_complete is False when a required signal's last
        known value is older than `window_s` (stale) even if present.
        """
        if not all(sig in self._latest for sig in REQUIRED_SIGNALS):
            return None, False

        complete = all(
            now_ms - self._latest[sig].timestamp_ms <= self.window_ms
            for sig in REQUIRED_SIGNALS
        )
        values = {sig: self._latest[sig].value for sig in REQUIRED_SIGNALS}
        score = compute_news2(values, copd_flag=self.copd_flag)
        return score, complete
