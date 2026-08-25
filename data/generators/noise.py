"""Transport/measurement noise injection — packet loss, outlier spikes,
sensor dropout, clock drift. A configurable wrapper layered on top of the
base generators, driven by `noise_seed` (independent of each generator's
own `signal_seed`). Stress-tests EWS window completeness under load
(see plan-detailed.md L1).
"""

import random
from dataclasses import dataclass


@dataclass
class NoiseConfig:
    packet_loss_rate: float = 0.0      # probability a reading is dropped in transit
    spike_probability: float = 0.0     # probability of a single-sample outlier spike
    # Spike size is relative to the reading's own value (fraction, e.g. 0.10 = +/-10%),
    # not an absolute unit — an absolute magnitude appropriate for HR (bpm, ~40-200)
    # is wildly out of range for temperature (degC, ~35-42) or SpO2 (%, bounded 0-100).
    spike_magnitude_pct: float = 0.10
    dropout_probability: float = 0.0   # probability a dropout window starts on this tick
    dropout_duration_s: float = 0.0    # length of a dropout window once triggered
    clock_drift_ms: int = 0            # max +/- device-timestamp jitter


class NoiseInjector:
    """Per-patient noise state, seeded independently of the signal generators."""

    def __init__(self, config: NoiseConfig, noise_seed: int | None = None) -> None:
        self.config = config
        self._rng = random.Random(noise_seed)
        self._dropout_until_ms: dict[str, int] = {}

    def apply(self, signal_type: str, value, timestamp_ms: int):
        """Return (value_or_None, adjusted_timestamp_ms).

        `value is None` means the reading was dropped (packet loss or an
        active dropout window) — the caller must not publish it.
        """
        cfg = self.config

        if timestamp_ms < self._dropout_until_ms.get(signal_type, 0):
            return None, timestamp_ms

        if cfg.dropout_duration_s > 0 and self._rng.random() < cfg.dropout_probability:
            self._dropout_until_ms[signal_type] = timestamp_ms + int(cfg.dropout_duration_s * 1000)
            return None, timestamp_ms

        if self._rng.random() < cfg.packet_loss_rate:
            return None, timestamp_ms

        if isinstance(value, dict):
            noisy = dict(value)
            if self._rng.random() < cfg.spike_probability:
                key = self._rng.choice(list(noisy.keys()))
                noisy[key] *= 1 + self._rng.uniform(-cfg.spike_magnitude_pct, cfg.spike_magnitude_pct)
        else:
            noisy = value
            if self._rng.random() < cfg.spike_probability:
                noisy *= 1 + self._rng.uniform(-cfg.spike_magnitude_pct, cfg.spike_magnitude_pct)

        jitter = self._rng.randint(-cfg.clock_drift_ms, cfg.clock_drift_ms) if cfg.clock_drift_ms else 0
        return noisy, timestamp_ms + jitter
