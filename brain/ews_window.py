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

from brain.ews_scorer import News2Assessment, REQUIRED_SIGNALS, assess_news2


@dataclass
class _Reading:
    value: float
    timestamp_ms: int


class PatientEWSState:
    def __init__(
        self,
        patient_id: str,
        window_s: float = 60.0,
        *,
        spo2_scale: int = 1,
    ) -> None:
        self.patient_id = patient_id
        if spo2_scale not in (1, 2):
            raise ValueError(f"spo2_scale must be 1 or 2, got {spo2_scale!r}")
        self.spo2_scale = spo2_scale
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
        known value is older than `window_s` (stale). Incomplete windows are
        never scored.
        """
        assessment, complete = self.composite_assessment(now_ms)
        return (assessment.total_score if assessment else None), complete

    def composite_assessment(self, now_ms: int) -> tuple[News2Assessment | None, bool]:
        """Return the assessment only when every required reading is fresh."""
        if not all(sig in self._latest for sig in REQUIRED_SIGNALS):
            return None, False

        complete = all(
            now_ms - self._latest[sig].timestamp_ms <= self.window_ms
            for sig in REQUIRED_SIGNALS
        )
        if not complete:
            return None, False
        values = {sig: self._latest[sig].value for sig in REQUIRED_SIGNALS}
        return assess_news2(values, spo2_scale=self.spo2_scale), True
