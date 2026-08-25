"""The three compared alarm-scoring approaches, sharing one pipeline.

Only the scoring layer differs (see plan-detailed.md "The Three Compared
Approaches"):

  A - Per-signal threshold  -> brain/evaluator.py (pre-existing, unchanged)
  B - Batch composite EWS   -> NEWS2 recomputed on a fixed tick (60s default)
  C - Streaming composite EWS -> NEWS2 recomputed on every incoming reading

B and C share the same underlying scorer (brain/ews_scorer.py via
brain/ews_window.py) — the cadence of invocation is the entire difference,
which is exactly the comparison the thesis makes.
"""

from dataclasses import dataclass

from brain.evaluator import evaluate_message
from brain.ews_scorer import alarm_level
from brain.ews_window import PatientEWSState

APPROACH_A = "A"
APPROACH_B = "B"
APPROACH_C = "C"

BATCH_TICK_MS = 60_000  # Approach B recomputation interval


@dataclass
class ScoredAlarm:
    scoring_approach: str
    alarm_level: str
    news2_score: int | None  # None for Approach A (no composite score)
    window_complete: bool


def score_approach_a(signal_type: str, value) -> list[ScoredAlarm]:
    """Per-signal threshold — fires independently per signal, no composite score."""
    return [
        ScoredAlarm(APPROACH_A, level, news2_score=None, window_complete=True)
        for _sig, _val, level in evaluate_message(signal_type, value)
    ]


def score_composite(state: PatientEWSState, now_ms: int, scoring_approach: str) -> ScoredAlarm | None:
    """Shared B/C scoring point. Returns None if the window has never been fully seeded."""
    score, complete = state.composite_score(now_ms)
    if score is None:
        return None
    return ScoredAlarm(scoring_approach, alarm_level(score), news2_score=score, window_complete=complete)


class BatchScheduler:
    """Tracks per-patient last-tick time so Approach B fires on a fixed cadence
    independent of message arrival (unlike C, which re-scores on every message).
    """

    def __init__(self, tick_ms: int = BATCH_TICK_MS) -> None:
        self.tick_ms = tick_ms
        self._last_tick: dict[str, int] = {}

    def due(self, patient_id: str, now_ms: int) -> bool:
        last = self._last_tick.get(patient_id)
        if last is None or now_ms - last >= self.tick_ms:
            self._last_tick[patient_id] = now_ms
            return True
        return False
