"""Kafka fault experiments with broker-free orchestration and measurable results.

Live runners only need to implement :class:`KafkaFaultAdapter`.  The accounting
and scenario ordering remain testable without Docker or a Kafka installation.
Kafka ordering is partition-local, so this module deliberately never reports a
global ordering violation across partitions.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Callable, Iterable, Mapping, Protocol

from confluent_kafka.schema_registry.error import SchemaRegistryError

from kafka_path.settings import KafkaSettings


@dataclass(frozen=True, order=True)
class KafkaRecordObservation:
    """Stable identity and broker position observed by the experiment consumer."""

    message_id: str
    partition: int
    offset: int


@dataclass(frozen=True)
class OffsetAccounting:
    expected: int
    received: int
    unique_received: int
    missing: int
    duplicates: int
    unexpected: int
    offset_replays: int
    partition_order_violations: int
    offset_gaps: int
    delivery_pct: float


def account_offsets(
    expected_ids: Iterable[str], observations: Iterable[KafkaRecordObservation]
) -> OffsetAccounting:
    """Measure loss, duplicate delivery, replay and partition-local ordering."""
    expected_list = list(expected_ids)
    if len(expected_list) != len(set(expected_list)):
        raise ValueError("expected message ids must be unique")
    expected = set(expected_list)
    observed = list(observations)
    expected_observed = [item for item in observed if item.message_id in expected]
    counts = Counter(item.message_id for item in expected_observed)
    positions = Counter((item.partition, item.offset) for item in observed)
    by_partition: dict[int, list[int]] = defaultdict(list)
    for item in observed:
        by_partition[item.partition].append(item.offset)

    violations = 0
    gaps = 0
    for offsets in by_partition.values():
        violations += sum(current < previous for previous, current in zip(offsets, offsets[1:]))
        # Gaps are calculated over unique broker positions. Replays neither
        # introduce nor conceal a gap.
        unique_offsets = sorted(set(offsets))
        gaps += sum(max(0, current - previous - 1) for previous, current in zip(unique_offsets, unique_offsets[1:]))

    unique_received = len(counts)
    return OffsetAccounting(
        expected=len(expected_list),
        received=len(observed),
        unique_received=unique_received,
        missing=len(expected - counts.keys()),
        duplicates=sum(count - 1 for count in counts.values()),
        unexpected=sum(item.message_id not in expected for item in observed),
        offset_replays=sum(count - 1 for count in positions.values()),
        partition_order_violations=violations,
        offset_gaps=gaps,
        delivery_pct=round(100 * unique_received / len(expected_list), 6) if expected_list else 100.0,
    )


@dataclass
class RebalanceState:
    assignments: int = 0
    revocations: int = 0
    lost: int = 0
    generations: list[int] = field(default_factory=list)

    def assigned(self, generation: int) -> None:
        self.assignments += 1
        self.generations.append(generation)

    def revoked(self) -> None:
        self.revocations += 1

    def partitions_lost(self) -> None:
        self.lost += 1

    @property
    def generation_changes(self) -> int:
        return sum(a != b for a, b in zip(self.generations, self.generations[1:]))


class KafkaFaultAdapter(Protocol):
    """Boundary implemented by a live Kafka/Docker runner or an in-memory fake."""

    def start(self, group_id: str) -> None: ...
    def publish(self, message_id: str) -> None: ...
    def restart_broker(self) -> None: ...
    def restart_consumer(self, group_id: str) -> None: ...
    def trigger_rebalance(self, group_id: str) -> None: ...
    def observations(self, timeout_s: float) -> list[KafkaRecordObservation]: ...
    def rebalance_state(self) -> RebalanceState: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class KafkaFaultResult:
    scenario: str
    group_id: str
    accounting: OffsetAccounting
    rebalance: RebalanceState
    recovery_ms: float
    timed_out: bool
    provenance: Mapping[str, object]

    def as_record(self) -> dict[str, object]:
        result = asdict(self)
        return result


class KafkaFaultHarness:
    def __init__(
        self,
        adapter: KafkaFaultAdapter,
        settings: KafkaSettings,
        *,
        timeout_s: float = 10.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.adapter = adapter
        self.settings = settings
        self.timeout_s = timeout_s
        self.clock = clock

    def _run(self, scenario: str, count: int, fault: Callable[[str], None]) -> KafkaFaultResult:
        if count < 2:
            raise ValueError("count must be at least 2")
        group_id = f"{self.settings.group_id}-{scenario}"
        expected = [f"{scenario}-{index}" for index in range(count)]
        midpoint = count // 2
        self.adapter.start(group_id)
        for message_id in expected[:midpoint]:
            self.adapter.publish(message_id)
        fault_started = self.clock()
        fault(group_id)
        for message_id in expected[midpoint:]:
            self.adapter.publish(message_id)
        observed = self.adapter.observations(self.timeout_s)
        recovered = self.clock()
        accounting = account_offsets(expected, observed)
        return KafkaFaultResult(
            scenario=scenario,
            group_id=group_id,
            accounting=accounting,
            # Adapters commonly maintain one mutable callback tracker. Snapshot
            # it so later scenarios cannot rewrite earlier evidence rows.
            rebalance=RebalanceState(**asdict(self.adapter.rebalance_state())),
            recovery_ms=round((recovered - fault_started) * 1000, 3),
            timed_out=accounting.missing > 0,
            provenance=normalized_provenance(self.settings),
        )

    def broker_restart(self, count: int) -> KafkaFaultResult:
        return self._run("broker_restart", count, lambda _group: self.adapter.restart_broker())

    def consumer_restart(self, count: int) -> KafkaFaultResult:
        return self._run("consumer_restart", count, self.adapter.restart_consumer)

    def consumer_group_rebalance(self, count: int) -> KafkaFaultResult:
        return self._run("consumer_group_rebalance", count, self.adapter.trigger_rebalance)

    def run_all(self, count: int) -> list[KafkaFaultResult]:
        try:
            return [
                self.broker_restart(count),
                self.consumer_restart(count),
                self.consumer_group_rebalance(count),
            ]
        finally:
            self.adapter.close()


class SchemaOutcome(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    COMPATIBLE_ACCEPTED = "compatible_accepted"
    COMPATIBLE_REJECTED = "compatible_rejected"
    INCOMPATIBLE_REJECTED = "incompatible_rejected"
    INCOMPATIBLE_ACCEPTED = "incompatible_accepted"


def classify_registry_error(error: Exception | None) -> SchemaOutcome:
    """Classify availability without treating an unknown schema as an outage."""
    if error is None:
        return SchemaOutcome.AVAILABLE
    if isinstance(error, SchemaRegistryError) and error.http_status_code >= 500:
        return SchemaOutcome.UNAVAILABLE
    raise error


def classify_schema_candidate(*, expected_compatible: bool, accepted: bool) -> SchemaOutcome:
    if expected_compatible:
        return SchemaOutcome.COMPATIBLE_ACCEPTED if accepted else SchemaOutcome.COMPATIBLE_REJECTED
    return SchemaOutcome.INCOMPATIBLE_ACCEPTED if accepted else SchemaOutcome.INCOMPATIBLE_REJECTED


@dataclass(frozen=True)
class SchemaExperimentResult:
    availability: SchemaOutcome
    compatible_candidate: SchemaOutcome | None
    incompatible_candidate: SchemaOutcome | None
    error: str | None = None


class SchemaRegistryProbe(Protocol):
    def get_compatibility(self, *, subject_name: str) -> str: ...

    def test_compatibility_all_versions(
        self, subject_name: str, candidate: object, *, normalize: bool
    ) -> bool: ...


def run_schema_experiment(
    registry: SchemaRegistryProbe,
    *,
    subject: str,
    compatible_candidate: object,
    incompatible_candidate: object,
) -> SchemaExperimentResult:
    """Probe availability and both evolution controls without registering either."""
    try:
        registry.get_compatibility(subject_name=subject)
        compatible_accepted = registry.test_compatibility_all_versions(
            subject, compatible_candidate, normalize=True
        )
        incompatible_accepted = registry.test_compatibility_all_versions(
            subject, incompatible_candidate, normalize=True
        )
    except SchemaRegistryError as error:
        availability = classify_registry_error(error)
        return SchemaExperimentResult(availability, None, None, str(error))
    return SchemaExperimentResult(
        availability=SchemaOutcome.AVAILABLE,
        compatible_candidate=classify_schema_candidate(
            expected_compatible=True, accepted=compatible_accepted
        ),
        incompatible_candidate=classify_schema_candidate(
            expected_compatible=False, accepted=incompatible_accepted
        ),
    )


def normalized_provenance(settings: KafkaSettings) -> dict[str, object]:
    """Return comparable effective config plus a stable canonical fingerprint."""
    effective = {
        "transport": "kafka",
        "bootstrap_servers": settings.bootstrap_servers,
        "schema_registry_url": settings.schema_registry_url,
        "vitals_topic": settings.vitals_topic,
        "dlq_topic": settings.dlq_topic,
        "group_id": settings.group_id,
        "compatibility": settings.compatibility,
        "producer": settings.producer_config(),
        "consumer": settings.consumer_config(),
        "semantics": {
            "delivery": "at_least_once",
            "ordering_scope": "partition",
            "commit": "synchronous_after_handler_or_dlq",
        },
    }
    canonical = json.dumps(effective, sort_keys=True, separators=(",", ":"))
    return {**effective, "config_sha256": hashlib.sha256(canonical.encode()).hexdigest()}
