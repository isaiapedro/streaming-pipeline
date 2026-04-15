import random
from .base_generator import BaseGenerator

_WALK_SIGMA = 1.5   # step size per reading (bpm)
_DRIFT      = 0.05  # mean-reversion strength (pulls back toward baseline)
_MIN, _MAX  = 20.0, 220.0


class HeartRateGenerator(BaseGenerator):
    """Gaussian random walk with mean-reversion around patient baseline."""

    def _init_state(self) -> None:
        b = self.profile["baselines"]["heart_rate"]
        self._mean = b["mean"]
        self._std  = b["std"]
        self._current = float(self._mean)

    def generate(self, timestamp: int) -> float:
        # Random walk step
        step = random.gauss(0, _WALK_SIGMA)
        # Mean-reversion: nudge back toward baseline
        reversion = _DRIFT * (self._mean - self._current)
        self._current += step + reversion
        self._current = max(_MIN, min(_MAX, self._current))
        return round(self._current, 1)
