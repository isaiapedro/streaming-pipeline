"""Environment-backed settings for the isolated Kafka comparison path."""

from __future__ import annotations

import os
from dataclasses import dataclass


_COMPATIBILITY_LEVELS = {
    "BACKWARD",
    "BACKWARD_TRANSITIVE",
    "FORWARD",
    "FORWARD_TRANSITIVE",
    "FULL",
    "FULL_TRANSITIVE",
    "NONE",
}


@dataclass(frozen=True)
class KafkaSettings:
    bootstrap_servers: str = "localhost:19092"
    schema_registry_url: str = "http://localhost:18081"
    vitals_topic: str = "vitals.protobuf.v1"
    dlq_topic: str = "vitals.dlq.protobuf.v1"
    group_id: str = "brain-kafka-v1"
    compatibility: str = "BACKWARD_TRANSITIVE"

    def __post_init__(self) -> None:
        if not self.bootstrap_servers:
            raise ValueError("Kafka bootstrap_servers must not be empty")
        if not self.schema_registry_url:
            raise ValueError("Schema Registry URL must not be empty")
        if not self.vitals_topic or not self.dlq_topic:
            raise ValueError("Kafka topic names must not be empty")
        if not self.group_id:
            raise ValueError("Kafka group_id must not be empty")
        if self.vitals_topic == self.dlq_topic:
            raise ValueError("Kafka vitals and DLQ topics must be different")
        if self.compatibility not in _COMPATIBILITY_LEVELS:
            raise ValueError(f"Unsupported Schema Registry compatibility: {self.compatibility}")

    @classmethod
    def from_env(cls) -> "KafkaSettings":
        overridden_topics = [
            name
            for name, expected in (
                ("KAFKA_VITALS_TOPIC", cls.vitals_topic),
                ("KAFKA_DLQ_TOPIC", cls.dlq_topic),
            )
            if os.getenv(name, expected) != expected
        ]
        if overridden_topics:
            raise ValueError(
                "Kafka topic names are fixed by the provisioned research contract; "
                f"unsupported overrides: {', '.join(overridden_topics)}"
            )
        return cls(
            bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", cls.bootstrap_servers),
            schema_registry_url=os.getenv("SCHEMA_REGISTRY_URL", cls.schema_registry_url),
            vitals_topic=cls.vitals_topic,
            dlq_topic=cls.dlq_topic,
            group_id=os.getenv("KAFKA_GROUP_ID", cls.group_id),
            compatibility=os.getenv("KAFKA_SCHEMA_COMPATIBILITY", cls.compatibility).upper(),
        )

    def producer_config(self) -> dict[str, object]:
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "enable.idempotence": True,
            "acks": "all",
            "allow.auto.create.topics": False,
        }

    def consumer_config(self) -> dict[str, object]:
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.group_id,
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "auto.offset.reset": "earliest",
            "isolation.level": "read_committed",
            "allow.auto.create.topics": False,
        }

    @property
    def vitals_subject(self) -> str:
        return f"{self.vitals_topic}-value"

    @property
    def dlq_subject(self) -> str:
        return f"{self.dlq_topic}-value"
