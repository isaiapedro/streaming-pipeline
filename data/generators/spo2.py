import random
from .base_generator import BaseGenerator

_DESAT_PROB  = 0.02   # 2 % chance of starting a desaturation event each step
_DESAT_DROP  = 5.0    # max drop during a desat (%)
_RECOVERY    = 0.3    # SpO2 units recovered per step after desat
_WALK_SIGMA  = 0.3
_DRIFT       = 0.08
_MIN, _MAX   = 70.0, 100.0


class SpO2Generator(BaseGenerator):
    """Beta-distributed SpO2 with occasional realistic desaturation events."""

    def _init_state(self) -> None:
        b = self.profile["baselines"]["spo2"]
        self._mean    = b["mean"]
        self._std     = b["std"]
        self._current = float(self._mean)
        self._desat_target: float | None = None

    def generate(self, timestamp: int) -> float:
        # Trigger a new desaturation event
        if self._desat_target is None and random.random() < _DESAT_PROB:
            drop = random.uniform(2.0, _DESAT_DROP)
            self._desat_target = max(_MIN, self._current - drop)

        if self._desat_target is not None:
            # Move toward the desat nadir
            if self._current > self._desat_target + 0.5:
                self._current -= random.uniform(0.5, 1.5)
            else:
                # Recovery phase
                self._current += _RECOVERY
                if self._current >= self._mean - 0.5:
                    self._desat_target = None
        else:
            # Normal random walk with mean-reversion
            step = random.gauss(0, _WALK_SIGMA)
            reversion = _DRIFT * (self._mean - self._current)
            self._current += step + reversion

        self._current = max(_MIN, min(_MAX, self._current))
        return round(self._current, 1)
