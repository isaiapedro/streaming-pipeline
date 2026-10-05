#!/usr/bin/env python3
"""Transport-neutral fault experiment orchestration.

The live NATS/MQTT implementations can expose the small ``FaultAdapter``
contract below, while CI uses an in-memory adapter.  Keeping fault scheduling
separate from broker clients makes the experiment phases and their accounting
identical across transports.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from typing import Awaitable, Callable, Protocol


class FaultAdapter(Protocol):
    transport: str

    async def start(self, consumer_id: str) -> None: ...
    async def publish(self, message_id: int) -> None: ...
    async def disconnect_publisher(self) -> None: ...
    async def reconnect_publisher(self) -> None: ...
    async def set_consumer_online(self, online: bool) -> None: ...
    async def restart_broker(self) -> None: ...
    async def received_ids(self, timeout_s: float) -> list[int]: ...
    async def resource_snapshot(self) -> dict[str, float | int | str | None]: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class DeliveryAccounting:
    sent: int
    received: int
    unique_received: int
    missing: int
    duplicates: int
    out_of_order: int
    delivery_pct: float


def account_delivery(expected_ids: list[int], received_ids: list[int]) -> DeliveryAccounting:
    """Account delivery without hiding duplicates or unexpected records."""
    expected = set(expected_ids)
    observed_expected = [item for item in received_ids if item in expected]
    unique = set(observed_expected)
    duplicates = len(observed_expected) - len(unique)
    # Count adjacent inversions. This remains meaningful in the presence of
    # duplicates and does not pretend to be a global sorting metric.
    out_of_order = sum(
        current < previous
        for previous, current in zip(observed_expected, observed_expected[1:])
    )
    sent = len(expected_ids)
    return DeliveryAccounting(
        sent=sent,
        received=len(received_ids),
        unique_received=len(unique),
        missing=len(expected - unique),
        duplicates=duplicates,
        out_of_order=out_of_order,
        delivery_pct=round(100.0 * len(unique) / sent, 6) if sent else 100.0,
    )


@dataclass
class FaultResult:
    transport: str
    scenario: str
    accounting: DeliveryAccounting
    fault_started_monotonic_s: float
    recovery_s: float | None
    timed_out: bool
    resources_before: dict[str, float | int | str | None] = field(default_factory=dict)
    resources_after: dict[str, float | int | str | None] = field(default_factory=dict)
    notes: str = ""

    def as_record(self) -> dict:
        record = asdict(self)
        record["accounting"] = asdict(self.accounting)
        return record


class FaultHarness:
    """Run controlled, repeatable fault phases against one transport adapter."""

    def __init__(
        self,
        adapter: FaultAdapter,
        *,
        settle_timeout_s: float = 10.0,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if settle_timeout_s <= 0:
            raise ValueError("settle_timeout_s must be positive")
        self.adapter = adapter
        self.timeout = settle_timeout_s
        self.clock = clock

    async def _finish(
        self,
        scenario: str,
        expected: list[int],
        fault_started: float,
        recovered_at: float | None,
        before: dict,
        notes: str,
    ) -> FaultResult:
        received = await self.adapter.received_ids(self.timeout)
        accounting = account_delivery(expected, received)
        return FaultResult(
            transport=self.adapter.transport,
            scenario=scenario,
            accounting=accounting,
            fault_started_monotonic_s=fault_started,
            recovery_s=None if recovered_at is None else recovered_at - fault_started,
            timed_out=accounting.missing > 0,
            resources_before=before,
            resources_after=await self.adapter.resource_snapshot(),
            notes=notes,
        )

    async def controlled_disconnect(self, n: int) -> FaultResult:
        """Drop only the publisher halfway through an acknowledged sequence."""
        expected = list(range(n))
        await self.adapter.start("fault-disconnect")
        before = await self.adapter.resource_snapshot()
        midpoint = n // 2
        for item in expected[:midpoint]:
            await self.adapter.publish(item)
        fault_started = self.clock()
        await self.adapter.disconnect_publisher()
        await self.adapter.reconnect_publisher()
        recovered_at = self.clock()
        for item in expected[midpoint:]:
            await self.adapter.publish(item)
        return await self._finish(
            "controlled_disconnect", expected, fault_started, recovered_at, before,
            "publisher disconnected; durable consumer remained online",
        )

    async def restart_during_traffic(self, n: int) -> FaultResult:
        """Restart the broker at the midpoint and resume acknowledged publishing."""
        expected = list(range(n))
        await self.adapter.start("fault-restart")
        before = await self.adapter.resource_snapshot()
        midpoint = n // 2
        for item in expected[:midpoint]:
            await self.adapter.publish(item)
        fault_started = self.clock()
        await self.adapter.restart_broker()
        await self.adapter.reconnect_publisher()
        recovered_at = self.clock()
        for item in expected[midpoint:]:
            await self.adapter.publish(item)
        return await self._finish(
            "broker_restart_during_traffic", expected, fault_started, recovered_at, before,
            "broker restarted between two acknowledged publish phases",
        )

    async def offline_recovery(self, n: int) -> FaultResult:
        """Publish while a durable consumer is offline, then reconnect it."""
        expected = list(range(n))
        await self.adapter.start("fault-offline")
        before = await self.adapter.resource_snapshot()
        await self.adapter.set_consumer_online(False)
        fault_started = self.clock()
        for item in expected:
            await self.adapter.publish(item)
        await self.adapter.set_consumer_online(True)
        recovered_at = self.clock()
        return await self._finish(
            "offline_durable_recovery", expected, fault_started, recovered_at, before,
            "persistent/durable consumer reconnected after acknowledged publishes",
        )

    async def run_all(self, n: int) -> list[FaultResult]:
        if n < 2:
            raise ValueError("n must be at least 2")
        try:
            return [
                await self.controlled_disconnect(n),
                await self.restart_during_traffic(n),
                await self.offline_recovery(n),
            ]
        finally:
            await self.adapter.close()


async def run_pair(
    nats_adapter: FaultAdapter,
    mqtt_adapter: FaultAdapter,
    n: int,
    *,
    settle_timeout_s: float = 10.0,
) -> list[dict]:
    """Run the same matrix concurrently and return flat serializable records."""
    results = await asyncio.gather(
        FaultHarness(nats_adapter, settle_timeout_s=settle_timeout_s).run_all(n),
        FaultHarness(mqtt_adapter, settle_timeout_s=settle_timeout_s).run_all(n),
    )
    return [item.as_record() for transport_results in results for item in transport_results]
