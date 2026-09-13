"""Derive operational alarm episodes from repeated scoring-state observations.

This analysis layer does not change any A/B/C scoring definition. An episode
opens on the first alarming observation and closes only after the state has
remained clear for ``clear_hold_ms``. This prevents every above-threshold
message from being counted as a separate alarm delivered to a clinician.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlarmEpisode:
    """A contiguous interval in which an alarm is operationally active."""

    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


class AlarmEpisodeTracker:
    """Convert alarm-state observations into debounced alarm episodes."""

    def __init__(self, clear_hold_ms: int = 10_000) -> None:
        if clear_hold_ms < 0:
            raise ValueError("clear_hold_ms must be non-negative")
        self.clear_hold_ms = clear_hold_ms
        self.episodes: list[AlarmEpisode] = []
        self._episode_start: int | None = None
        self._clear_candidate: int | None = None
        self._last_timestamp: int | None = None

    @property
    def active(self) -> bool:
        return self._episode_start is not None

    def observe(self, timestamp_ms: int, alarming: bool) -> None:
        if self._last_timestamp is not None and timestamp_ms < self._last_timestamp:
            raise ValueError("alarm observations must be chronological")
        self._last_timestamp = timestamp_ms

        if alarming:
            self._clear_candidate = None
            if self._episode_start is None:
                self._episode_start = timestamp_ms
            return

        if self._episode_start is None:
            return
        if self._clear_candidate is None:
            self._clear_candidate = timestamp_ms
        if timestamp_ms - self._clear_candidate >= self.clear_hold_ms:
            self._close(self._clear_candidate + self.clear_hold_ms)

    def finalize(self, end_ms: int) -> list[AlarmEpisode]:
        """Close any remaining episode at its confirmed clear time or run end."""

        if self._episode_start is not None:
            if (
                self._clear_candidate is not None
                and end_ms - self._clear_candidate >= self.clear_hold_ms
            ):
                close_ms = self._clear_candidate + self.clear_hold_ms
            else:
                close_ms = end_ms
            self._close(close_ms)
        return list(self.episodes)

    def _close(self, end_ms: int) -> None:
        assert self._episode_start is not None
        self.episodes.append(AlarmEpisode(self._episode_start, end_ms))
        self._episode_start = None
        self._clear_candidate = None
