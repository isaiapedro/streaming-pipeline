"""Kafka topic contracts and parser for provisioning output."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class KafkaTopicContract:
    name: str
    partitions: int
    replication_factor: int = 1
    required_configs: tuple[tuple[str, str], ...] = ()

    def assert_describe(self, output: str) -> None:
        partition_match = re.search(r"PartitionCount:\s*(\d+)", output)
        replication_match = re.search(r"ReplicationFactor:\s*(\d+)", output)
        errors = []
        if not re.search(rf"Topic:\s*{re.escape(self.name)}(?:\s|$)", output):
            errors.append("topic name missing")
        if not partition_match or int(partition_match.group(1)) != self.partitions:
            errors.append(f"partitions must equal {self.partitions}")
        if not replication_match or int(replication_match.group(1)) != self.replication_factor:
            errors.append(f"replication factor must equal {self.replication_factor}")
        for key, value in self.required_configs:
            if not re.search(rf"(?:^|,){re.escape(key)}={re.escape(value)}(?:,|\s|$)", output):
                errors.append(f"{key} must equal {value}")
        if errors:
            raise RuntimeError(f"Kafka topic {self.name} configuration drift: {'; '.join(errors)}")


VITALS_TOPIC = KafkaTopicContract("vitals.protobuf.v1", 3)
DLQ_TOPIC = KafkaTopicContract(
    "vitals.dlq.protobuf.v1",
    1,
    required_configs=(("cleanup.policy", "compact,delete"), ("retention.ms", "86400000")),
)
TOPIC_CONTRACTS = {contract.name: contract for contract in (VITALS_TOPIC, DLQ_TOPIC)}
