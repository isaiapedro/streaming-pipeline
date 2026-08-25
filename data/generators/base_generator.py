import random
from abc import ABC, abstractmethod
from typing import Any


class BaseGenerator(ABC):
    """Abstract base for all vital-sign generators.

    Generators are stateful — each call to generate() advances an internal
    random walk so successive readings are physiologically correlated.

    `signal_seed` seeds this generator's private RNG. Two generators built
    with the same seed produce identical trajectories — required for
    reproducible benchmark runs (same signal_seed across approaches A/B/C).
    Omit it (None) for live/demo mode, which falls back to os-random seeding.
    """

    def __init__(self, profile: dict, signal_seed: int | None = None) -> None:
        self.profile = profile
        self.patient_id: str = profile["patient_id"]
        self._rng = random.Random(signal_seed)
        self._init_state()

    @abstractmethod
    def _init_state(self) -> None:
        """Initialise internal state from self.profile baselines."""

    @abstractmethod
    def generate(self, timestamp: int) -> Any:
        """Return the next synthetic reading.

        Args:
            timestamp: Unix epoch in milliseconds (from the producer).

        Returns:
            A float (or dict for multi-value signals like blood_pressure).
        """
