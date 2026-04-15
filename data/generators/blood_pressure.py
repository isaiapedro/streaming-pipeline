import random
from .base_generator import BaseGenerator

_WALK_SIGMA_SYS = 2.0
_WALK_SIGMA_DIA = 1.5
_DRIFT          = 0.06
_CORRELATION    = 0.7   # shared noise component


class BloodPressureGenerator(BaseGenerator):
    """Correlated systolic/diastolic random walk.

    Returns a dict {"systolic": float, "diastolic": float}.
    """

    def _init_state(self) -> None:
        b = self.profile["baselines"]
        self._sys_mean = b["systolic_bp"]["mean"]
        self._dia_mean = b["diastolic_bp"]["mean"]
        self._sys = float(self._sys_mean)
        self._dia = float(self._dia_mean)

    def generate(self, timestamp: int) -> dict:
        shared = random.gauss(0, 1.0)  # correlated component

        sys_step = _CORRELATION * shared + (1 - _CORRELATION) * random.gauss(0, 1.0)
        dia_step = _CORRELATION * shared + (1 - _CORRELATION) * random.gauss(0, 1.0)

        self._sys += sys_step * _WALK_SIGMA_SYS + _DRIFT * (self._sys_mean - self._sys)
        self._dia += dia_step * _WALK_SIGMA_DIA + _DRIFT * (self._dia_mean - self._dia)

        # Diastolic must stay below systolic with physiological gap
        self._dia = min(self._dia, self._sys - 20)
        self._sys = max(50.0, min(250.0, self._sys))
        self._dia = max(30.0, min(150.0, self._dia))

        return {
            "systolic":  round(self._sys, 1),
            "diastolic": round(self._dia, 1),
        }
