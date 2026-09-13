"""Versioned JetStream consumer contracts used by provisioning and runtime.

JetStream keeps durable-consumer configuration after a process exits.  Merely
passing a config to ``pull_subscribe`` does not update an existing durable, so
the application must verify the server-side config before processing data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, ReplayPolicy


@dataclass(frozen=True)
class NatsConsumerContract:
    durable_name: str
    filter_subject: str = "vitals.>"
    ack_wait_s: float = 30.0
    max_deliver: int = 3
    max_ack_pending: int = 500

    def as_config(self) -> ConsumerConfig:
        return ConsumerConfig(
            durable_name=self.durable_name,
            deliver_policy=DeliverPolicy.ALL,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=self.ack_wait_s,
            max_deliver=self.max_deliver,
            filter_subject=self.filter_subject,
            replay_policy=ReplayPolicy.INSTANT,
            max_ack_pending=self.max_ack_pending,
        )

    def assert_matches(self, actual: Any) -> None:
        """Raise with every mismatch instead of accepting broker defaults.

        ``actual`` may be nats.py's ``ConsumerConfig`` or the config mapping
        emitted by ``nats consumer info --json``.  CLI durations are encoded
        in nanoseconds; nats.py exposes them in seconds.
        """
        expected = {
            "durable_name": self.durable_name,
            "filter_subject": self.filter_subject,
            "ack_policy": "explicit",
            "ack_wait": self.ack_wait_s,
            "max_deliver": self.max_deliver,
            "max_ack_pending": self.max_ack_pending,
        }
        observed: dict[str, Any] = {}
        is_mapping = isinstance(actual, Mapping)
        for field in expected:
            value = actual.get(field) if is_mapping else getattr(actual, field, None)
            if hasattr(value, "value"):
                value = value.value
            if field == "ack_wait" and is_mapping and isinstance(value, (int, float)):
                value = value / 1_000_000_000
            observed[field] = value

        drift = {
            field: {"expected": expected[field], "actual": observed[field]}
            for field in expected
            if observed[field] != expected[field]
        }
        if drift:
            details = ", ".join(
                f"{field}={values['actual']!r} (expected {values['expected']!r})"
                for field, values in sorted(drift.items())
            )
            raise RuntimeError(
                f"JetStream consumer {self.durable_name} configuration drift: {details}. "
                "Run scripts/create_streams.sh to reconcile mutable settings; "
                "an immutable-policy mismatch requires deliberate consumer recreation."
            )


BRAIN_CONSUMER = NatsConsumerContract("BRAIN")
LOCAL_SCORER_CONSUMER = NatsConsumerContract("LOCAL_SCORER")

CONSUMER_CONTRACTS = {
    contract.durable_name: contract
    for contract in (BRAIN_CONSUMER, LOCAL_SCORER_CONSUMER)
}


async def assert_server_consumer(js: Any, stream: str, contract: NatsConsumerContract) -> None:
    info = await js.consumer_info(stream, contract.durable_name)
    contract.assert_matches(info.config)
