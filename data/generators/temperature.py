import math
from .base_generator import BaseGenerator
import random

_WALK_SIGMA  = 0.05   # slow drift per reading (°C)
_DRIFT       = 0.03
_CIRCADIAN_A = 0.3    # amplitude of circadian swing (°C)
_MIN, _MAX   = 34.0, 42.0


class TemperatureGenerator(BaseGenerator):
    """Slow random walk with a superimposed circadian sinusoidal variation.

    Body temperature peaks in late afternoon (~18:00) and troughs around 04:00.
    """

    def _init_state(self) -> None:
        b = self.profile["baselines"]["temperature"]
        self._mean    = b["mean"]
        self._current = float(self._mean)

    def generate(self, timestamp: int) -> float:
        # Circadian offset: timestamp in ms → seconds → hours
        hour_of_day = (timestamp / 1000 / 3600) % 24
        # Peak at hour 18 (18:00), trough at 06:00 — shift by -6h from cosine peak
        circadian = _CIRCADIAN_A * math.sin(2 * math.pi * (hour_of_day - 6) / 24)

        step = random.gauss(0, _WALK_SIGMA)
        reversion = _DRIFT * (self._mean - self._current)
        self._current += step + reversion

        value = self._current + circadian
        value = max(_MIN, min(_MAX, value))
        return round(value, 2)
