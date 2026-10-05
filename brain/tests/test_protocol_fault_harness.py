import asyncio

import pytest

from scripts.protocol_fault_harness import FaultHarness, account_delivery, run_pair
from scripts.run_protocol_fault_experiment import build_evidence, write_atomic_json


class FakeAdapter:
    def __init__(self, transport="nats", transform=None):
        self.transport = transport
        self.transform = transform or (lambda values: values)
        self.messages = []
        self.visible = []
        self.online = True
        self.events = []

    async def start(self, consumer_id):
        self.messages.clear(); self.visible.clear(); self.online = True
        self.events.append(("start", consumer_id))

    async def publish(self, message_id):
        self.messages.append(message_id)
        if self.online:
            self.visible.append(message_id)

    async def disconnect_publisher(self): self.events.append(("disconnect", None))
    async def reconnect_publisher(self): self.events.append(("reconnect", None))
    async def restart_broker(self): self.events.append(("restart", None))

    async def set_consumer_online(self, online):
        self.online = online
        if online:
            self.visible = list(self.messages)

    async def received_ids(self, timeout_s):
        return self.transform(list(self.visible))

    async def resource_snapshot(self):
        return {"rss_bytes": 1024, "disk_bytes": 2048}

    async def close(self): self.events.append(("close", None))


def test_delivery_accounting_exposes_loss_duplicates_and_ordering():
    result = account_delivery([0, 1, 2, 3], [0, 2, 2, 1, 99])
    assert result.sent == 4
    assert result.received == 5
    assert result.unique_received == 3
    assert result.missing == 1
    assert result.duplicates == 1
    assert result.out_of_order == 1
    assert result.delivery_pct == 75.0


def test_controlled_disconnect_has_measurable_recovery_and_resources():
    ticks = iter([10.0, 10.25])
    adapter = FakeAdapter()
    result = asyncio.run(FaultHarness(adapter, clock=lambda: next(ticks)).controlled_disconnect(6))
    assert result.scenario == "controlled_disconnect"
    assert result.recovery_s == pytest.approx(0.25)
    assert result.accounting.delivery_pct == 100.0
    assert result.resources_before["rss_bytes"] == 1024
    assert adapter.events[-2:] == [("disconnect", None), ("reconnect", None)]


def test_offline_recovery_requires_durable_backlog_delivery():
    adapter = FakeAdapter(transform=lambda values: values[:-1])
    result = asyncio.run(FaultHarness(adapter).offline_recovery(5))
    assert result.timed_out is True
    assert result.accounting.missing == 1
    assert result.accounting.delivery_pct == 80.0


def test_restart_is_between_publish_phases_and_tracks_order():
    adapter = FakeAdapter(transform=lambda values: [0, 2, 1, *values[3:]])
    result = asyncio.run(FaultHarness(adapter).restart_during_traffic(6))
    assert result.accounting.out_of_order == 1
    assert ("restart", None) in adapter.events
    assert result.recovery_s is not None


def test_pair_produces_same_three_scenario_matrix_and_closes_adapters():
    nats = FakeAdapter("nats")
    mqtt = FakeAdapter("mqtt")
    records = asyncio.run(run_pair(nats, mqtt, 4))
    assert len(records) == 6
    assert {row["transport"] for row in records} == {"nats", "mqtt"}
    assert {row["scenario"] for row in records} == {
        "controlled_disconnect", "broker_restart_during_traffic", "offline_durable_recovery"
    }
    assert all(row["accounting"]["delivery_pct"] == 100.0 for row in records)
    assert nats.events[-1] == ("close", None)
    assert mqtt.events[-1] == ("close", None)


def test_run_all_rejects_meaningless_sample_and_still_closes_on_failure():
    adapter = FakeAdapter()
    with pytest.raises(ValueError, match="at least 2"):
        asyncio.run(FaultHarness(adapter).run_all(1))


def test_governed_fault_writer_passes_only_complete_lossless_matrix(tmp_path):
    records = asyncio.run(run_pair(FakeAdapter("nats"), FakeAdapter("mqtt"), 4))
    evidence = build_evidence(records, messages=4, provenance={"implementation_commit": "abc"})
    assert evidence["status"] == "passed"
    assert evidence["record_count"] == 6
    assert "hostname" not in evidence["provenance"]
    output = tmp_path / "faults.json"
    write_atomic_json(output, evidence)
    assert __import__("json").loads(output.read_text())["status"] == "passed"


def test_governed_fault_writer_fails_closed_on_missing_cell_or_delivery():
    records = asyncio.run(run_pair(FakeAdapter("nats"), FakeAdapter("mqtt"), 4))
    records.pop()
    records[0]["accounting"]["missing"] = 1
    evidence = build_evidence(records, messages=4, provenance={})
    assert evidence["status"] == "failed"
    assert any("missing matrix cells" in error for error in evidence["validation_errors"])
    assert any("missing deliveries" in error for error in evidence["validation_errors"])
