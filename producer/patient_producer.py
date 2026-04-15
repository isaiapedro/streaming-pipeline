"""Async NATS publisher for a single patient.

One PatientProducer spawns five signal tasks, each publishing on its own
interval to `vitals.{patient_id}.{signal_type}`.
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

log = logging.getLogger(__name__)

# Publish intervals per signal (seconds)
_INTERVALS: dict[str, float] = {
    "heart_rate":       2.0,
    "spo2":             2.0,
    "blood_pressure":   5.0,
    "respiratory_rate": 4.0,
    "temperature":      10.0,
}


class PatientProducer:
    def __init__(self, profile: dict, js: JetStreamContext) -> None:
        self.patient_id: str = profile["patient_id"]
        self._js = js
        self._generators = {
            "heart_rate":       HeartRateGenerator(profile),
            "spo2":             SpO2Generator(profile),
            "blood_pressure":   BloodPressureGenerator(profile),
            "respiratory_rate": RespiratoryRateGenerator(profile),
            "temperature":      TemperatureGenerator(profile),
        }

    async def run(self) -> None:
        """Launch all signal tasks concurrently and run until cancelled."""
        tasks = [
            asyncio.create_task(
                self._publish_loop(signal_type, interval),
                name=f"{self.patient_id}.{signal_type}",
            )
            for signal_type, interval in _INTERVALS.items()
        ]
        await asyncio.gather(*tasks)

    async def _publish_loop(self, signal_type: str, interval: float) -> None:
        while True:
            ts = int(time.time() * 1000)
            value: Any = self._generators[signal_type].generate(ts)

            payload = json.dumps(
                {"patient_id": self.patient_id, "signal_type": signal_type,
                 "value": value, "timestamp": ts}
            ).encode()

            subject = f"vitals.{self.patient_id}.{signal_type}"
            try:
                await self._js.publish(subject, payload)
                log.debug("%s → %s", subject, value)
            except Exception as exc:
                log.warning("Publish failed for %s: %s", subject, exc)

            await asyncio.sleep(interval)
