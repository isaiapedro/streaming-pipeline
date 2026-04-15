import random
from .base_generator import BaseGenerator

_DRIFT   = 0.1
_MIN, _MAX = 4, 60


class RespiratoryRateGenerator(BaseGenerator):
    """Poisson-like integer respiratory rate with mean-reversion."""

    def _init_state(self) -> None:
        b = self.profile["baselines"]["respiratory_rate"]
        self._mean    = b["mean"]
        self._current = float(self._mean)

    def generate(self, timestamp: int) -> int:
        # Poisson-like: step is ±1 or 0, biased toward mean
        reversion = _DRIFT * (self._mean - self._current)
        step = random.choice([-1, 0, 0, 1])  # integer steps
        self._current += step + reversion
        self._current = max(_MIN, min(_MAX, self._current))
        return int(round(self._current))
