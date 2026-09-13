"""Declared JetStream stream contracts for provisioning and verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class NatsStreamContract:
    name: str
    subjects: tuple[str, ...]
    max_age_s: float = 86_400.0
    storage: str = "file"
    retention: str = "limits"
    replicas: int = 1

    def assert_matches(self, actual: Any) -> None:
        is_mapping = isinstance(actual, Mapping)

        def read(name: str, default=None):
            value = actual.get(name, default) if is_mapping else getattr(actual, name, default)
            return value.value if hasattr(value, "value") else value

        max_age = read("max_age", 0)
        if is_mapping and isinstance(max_age, (int, float)):
            max_age = max_age / 1_000_000_000
        observed = {
            "name": read("name"),
            "subjects": tuple(sorted(read("subjects", ()) or ())),
            "max_age": max_age,
            "storage": read("storage"),
            "retention": read("retention"),
            "replicas": read("num_replicas", read("replicas")),
        }
        expected = {
            "name": self.name,
            "subjects": tuple(sorted(self.subjects)),
            "max_age": self.max_age_s,
            "storage": self.storage,
            "retention": self.retention,
            "replicas": self.replicas,
        }
        drift = {
            key: {"expected": expected[key], "actual": observed[key]}
            for key in expected
            if observed[key] != expected[key]
        }
        if drift:
            details = ", ".join(
                f"{key}={values['actual']!r} (expected {values['expected']!r})"
                for key, values in sorted(drift.items())
            )
            raise RuntimeError(f"JetStream stream {self.name} configuration drift: {details}")


VITALS_STREAM = NatsStreamContract("VITALS", ("vitals.>",))
VITALS_DLQ_STREAM = NatsStreamContract("VITALS_DLQ", ("dlq.vitals.>",))
ALARMS_STREAM = NatsStreamContract("ALARMS", ("alarms.>",), max_age_s=604_800.0)

STREAM_CONTRACTS = {
    contract.name: contract
    for contract in (VITALS_STREAM, VITALS_DLQ_STREAM, ALARMS_STREAM)
}
