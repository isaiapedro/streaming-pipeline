"""Async NATS publisher for a single patient.

One PatientProducer spawns five signal tasks, each publishing on its own
interval to `vitals.{patient_id}.{signal_type}`. Optionally overlays a
deterministic clinical Scenario (data/scenarios/definitions.py) and/or
transport noise (data/generators/noise.py) on top of each generator's
baseline stochastic output, and applies the inter-signal correlation
nudges (data/generators/correlation.py) using this patient's own latest
readings across signals.
"""

import asyncio
import json
import time
import logging
from typing import Any

import nats
from nats.js import JetStreamContext

from data.generators.heart_rate import HeartRateGenerator
from data.generators.spo2 import SpO2Generator
from data.generators.blood_pressure import BloodPressureGenerator
from data.generators.respiratory_rate import RespiratoryRateGenerator
from data.generators.temperature import TemperatureGenerator
from data.generators.correlation import correlated_delta
from data.generators.noise import NoiseInjector
from data.scenarios.definitions import Scenario

log = logging.getLogger(__name__)

# Publish intervals per signal (seconds)
_INTERVALS: dict[str, float] = {
    "heart_rate":       2.0,
    "spo2":             2.0,
    "blood_pressure":   5.0,
    "respiratory_rate": 4.0,
    "temperature":      10.0,
}

# scenario peak_deltas use "systolic_bp"/"diastolic_bp"; blood_pressure
# generator output/latest tracking uses the same flat keys internally here.
_BP_SUB_KEYS = {"systolic_bp": "systolic", "diastolic_bp": "diastolic"}


class PatientProducer:
    def __init__(
        self,
        profile: dict,
        js: JetStreamContext,
        signal_seed: int | None = None,
        noise_injector: NoiseInjector | None = None,
        scenario: Scenario | None = None,
    ) -> None:
        self.patient_id: str = profile["patient_id"]
        self._profile = profile
        self._js = js
        self._noise = noise_injector
        self._scenario = scenario
        self._start_ms: int | None = None
        # Distinct seeds per signal (derived from one base seed) keep signals
        # decorrelated at the RNG level — correlation is applied explicitly.
        seed = lambda offset: None if signal_seed is None else signal_seed + offset
        self._generators = {
            "heart_rate":       HeartRateGenerator(profile, seed(0)),
            "spo2":             SpO2Generator(profile, seed(1)),
            "blood_pressure":   BloodPressureGenerator(profile, seed(2)),
            "respiratory_rate": RespiratoryRateGenerator(profile, seed(3)),
            "temperature":      TemperatureGenerator(profile, seed(4)),
        }
        # Latest flat-keyed values across all signals, for correlation lookups.
        self._latest: dict[str, float] = {}

    async def run(self) -> None:
        """Launch all signal tasks concurrently and run until cancelled."""
        self._start_ms = int(time.time() * 1000)
        tasks = [
            asyncio.create_task(
                self._publish_loop(signal_type, interval),
                name=f"{self.patient_id}.{signal_type}",
            )
            for signal_type, interval in _INTERVALS.items()
        ]
        await asyncio.gather(*tasks)

    def _apply_scenario_and_correlation(self, signal_type: str, value: Any, elapsed_ms: int) -> Any:
        deltas = self._scenario.delta_at(elapsed_ms) if self._scenario else {}
        copd_flag = (
            self._scenario.copd_flag_override
            if self._scenario and self._scenario.copd_flag_override is not None
            else self._profile.get("copd_flag", False)
        )

        if signal_type == "blood_pressure":
            adjusted = dict(value)
            for flat_key, sub_key in _BP_SUB_KEYS.items():
                adjusted[sub_key] += deltas.get(flat_key, 0.0)
            return adjusted

        delta = deltas.get(signal_type, 0.0)
        delta += correlated_delta(signal_type, self._latest, self._profile["baselines"], copd_flag)
        return value + delta

    def _update_latest(self, signal_type: str, value: Any) -> None:
        if signal_type == "blood_pressure":
            self._latest["systolic_bp"] = value["systolic"]
            self._latest["diastolic_bp"] = value["diastolic"]
        else:
            self._latest[signal_type] = value

    async def _publish_loop(self, signal_type: str, interval: float) -> None:
        while True:
            ts = int(time.time() * 1000)
            elapsed_ms = ts - self._start_ms
            raw_value: Any = self._generators[signal_type].generate(ts)
            value = self._apply_scenario_and_correlation(signal_type, raw_value, elapsed_ms)
            self._update_latest(signal_type, value)

            publish_value, publish_ts = value, ts
            if self._noise is not None:
                publish_value, publish_ts = self._noise.apply(signal_type, value, ts)

            if publish_value is not None:
                payload = {
                    "patient_id": self.patient_id, "signal_type": signal_type,
                    "value": publish_value, "timestamp": publish_ts,
                }
                if self._scenario is not None:
                    payload["scenario_id"] = self._scenario.scenario_id
                    payload["onset_offset_ms"] = self._scenario.onset_offset_ms

                subject = f"vitals.{self.patient_id}.{signal_type}"
                try:
                    await self._js.publish(subject, json.dumps(payload).encode())
                    log.debug("%s → %s", subject, publish_value)
                except Exception as exc:
                    log.warning("Publish failed for %s: %s", subject, exc)
            else:
                log.debug("%s dropped (noise injection)", signal_type)

            await asyncio.sleep(interval)
