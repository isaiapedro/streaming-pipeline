"""Focused tests for the scale runner's bounded producer pipeline.

These tests deliberately use fakes and never open a broker connection.
"""

import asyncio
import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from schema import vitals_pb2
from scripts import run_scale_tier


def test_active_scale_spec_starts_at_t2():
    assert tuple(run_scale_tier.TIERS) == ("T2", "T3", "T4")
    assert "T1" not in run_scale_tier.TIERS


class _ScalarGenerator:
    def generate(self, _timestamp_ms):
        return 72.5


class _FakeJetStream:
    def __init__(self, *, delay=0, fail=False):
        self.delay = delay
        self.fail = fail
        self.messages = []

    async def publish(self, subject, payload):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("publish failed")
        self.messages.append((subject, payload))
        return object()


class _FakeProducer:
    patient_id = "P-SCALE-TEST"

    def __init__(self, js=None, signal_count=1):
        self._js = js or _FakeJetStream()
        self._generators = {
            f"signal_{index}": _ScalarGenerator() for index in range(signal_count)
        }


def test_producer_stats_finalize_computes_mean_without_mutating_input():
    stats = run_scale_tier._new_producer_stats()
    stats["schedule_samples"] = 4
    stats["schedule_lag_total_ms"] = 10.0

    result = run_scale_tier._finalize_producer_stats(stats)

    assert result["schedule_lag_mean_ms"] == pytest.approx(2.5)
    assert "schedule_samples" not in result
    assert "schedule_lag_total_ms" not in result
    assert stats["schedule_samples"] == 4


def test_make_scale_message_isolated_subject_and_valid_payload():
    producer = _FakeProducer()

    subject, raw = run_scale_tier._make_scale_message(producer, "signal_0", 123456)
    message = vitals_pb2.VitalSign.FromString(raw)

    assert subject == "scale.P-SCALE-TEST.signal_0"
    assert message.patient_id == "P-SCALE-TEST"
    assert message.signal_type == "signal_0"
    assert message.timestamp_ms == 123456
    assert message.scalar_value == pytest.approx(72.5)


@pytest.mark.asyncio
async def test_publish_one_records_ack_and_failure_counters():
    stats = run_scale_tier._new_producer_stats()
    await run_scale_tier._publish_one(_FakeJetStream(), "scale.ok", b"ok", stats)
    await run_scale_tier._publish_one(
        _FakeJetStream(fail=True), "scale.fail", b"fail", stats
    )

    assert stats["publish_attempted"] == 2
    assert stats["acknowledged"] == 1
    assert stats["publish_failed"] == 1
    assert stats["in_flight"] == 0
    assert stats["peak_in_flight"] == 1


@pytest.mark.asyncio
async def test_bounded_queue_counts_backpressure_without_blocking():
    stats = run_scale_tier._new_producer_stats()
    queue = asyncio.Queue(maxsize=1)
    queue.put_nowait(("occupied", b"payload"))
    stop = asyncio.Event()
    producer = _FakeProducer(signal_count=2)

    task = asyncio.create_task(
        run_scale_tier._run_all_signals(producer, 60.0, stats, stop, queue)
    )
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=0.2)

    assert stats["requested"] == 2
    assert stats["generated"] == 2
    assert stats["enqueued"] == 0
    assert stats["queue_full_drops"] == 2
    assert stats["publish_attempted"] == 0


@pytest.mark.asyncio
async def test_deadline_schedule_does_not_add_publish_time_to_interval():
    """A 30ms publish on a 20ms cadence should not become a 50ms cadence."""
    stats = run_scale_tier._new_producer_stats()
    producer = _FakeProducer(js=_FakeJetStream(delay=0.03))
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_scale_tier._run_all_signals(producer, 0.02, stats, stop)
    )
    await asyncio.sleep(0.105)
    stop.set()
    await asyncio.wait_for(task, timeout=0.2)

    # The scheduler does not add another full interval after publishing and it
    # explicitly skips overdue ticks instead of creating an unbounded burst.
    assert stats["acknowledged"] >= 3
    assert stats["schedule_lag_max_ms"] > 0
    assert stats["schedule_missed_ticks"] >= 1


@pytest.mark.asyncio
async def test_publish_worker_drains_queue_and_marks_tasks_done():
    stats = run_scale_tier._new_producer_stats()
    js = _FakeJetStream()
    queue = asyncio.Queue(maxsize=2)
    queue.put_nowait(("scale.a", b"a"))
    queue.put_nowait(("scale.b", b"b"))
    worker = asyncio.create_task(run_scale_tier._publish_worker(js, queue, stats))

    await asyncio.wait_for(queue.join(), timeout=0.2)
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)

    assert [subject for subject, _ in js.messages] == ["scale.a", "scale.b"]
    assert stats["publish_attempted"] == stats["acknowledged"] == 2


def test_write_result_preserves_json_and_flat_csv_compatibility(tmp_path):
    result = {
        "tier": "T2",
        "status": "executed",
        "producer_mode": "pipelined",
        "producer": {"requested": 10, "acknowledged": 9},
        "machine": {"logical_cpus": 12, "memory_bytes": None},
    }
    json_path = tmp_path / "result.json"
    csv_path = tmp_path / "result.csv"

    run_scale_tier.write_result(result, csv_path, json_path)

    assert json.loads(json_path.read_text()) == result
    with csv_path.open(newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["tier"] == "T2"
    assert row["producer_mode"] == "pipelined"
    assert row["machine_logical_cpus"] == "12"
    assert row["machine_memory_bytes"] == ""
    assert row["producer_requested"] == "10"
    assert row["producer_acknowledged"] == "9"


def test_write_result_remains_compatible_with_legacy_result_without_producer(tmp_path):
    result = {
        "tier": "T1",
        "status": "executed",
        "machine": {"logical_cpus": 4},
    }

    run_scale_tier.write_result(result, tmp_path / "legacy.csv", None)

    with (tmp_path / "legacy.csv").open(newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row == {"tier": "T1", "status": "executed", "machine_logical_cpus": "4"}


@pytest.mark.parametrize(
    "option,value",
    [("--publish-concurrency", "0"), ("--producer-queue-size", "0")],
)
def test_cli_rejects_nonpositive_pipeline_limits(option, value):
    script = Path(run_scale_tier.__file__)
    completed = subprocess.run(
        [sys.executable, str(script), "--tier", "T2", option, value],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert f"{option} must be at least 1" in completed.stderr
