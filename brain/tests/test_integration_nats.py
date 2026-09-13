"""Integration test: real NATS JetStream -> scoring (Approach A + composite C),
exercising the actual wire path instead of in-process simulation.

Requires a local NATS with the VITALS stream already created (see
`scripts/create_streams.sh`) — skips cleanly rather than failing when no
broker is running, so this doesn't break a plain `pytest` run on a machine
without Docker up.

Does NOT touch InfluxDB — this test verifies the NATS transport + scoring
logic only, deliberately avoiding writes to the real InfluxDB Cloud bucket
that `brain/main.py` would otherwise make (this test has no test-specific
InfluxDB target to write to safely).
"""

import os
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import nats
import pytest
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

from brain.approaches import BatchScheduler
from brain.main import _process
from brain.influx_writer import InfluxWriter
from config.settings import nats_connection_options
from brain.validation import DLQ_SUBJECT
from schema import vitals_pb2

def _skip_or_fail(message: str) -> None:
    if os.getenv("REQUIRE_NATS_INTEGRATION", "false").lower() == "true":
        pytest.fail(message)
    pytest.skip(message)


async def _try_connect():
    options = nats_connection_options()
    servers = options["servers"]

    def numeric_loopback(server):
        parsed = urlsplit(server)
        if parsed.hostname != "localhost":
            return server
        auth, separator, _host = parsed.netloc.rpartition("@")
        prefix = f"{auth}{separator}" if separator else ""
        port = f":{parsed.port}" if parsed.port is not None else ""
        return urlunsplit(parsed._replace(netloc=f"{prefix}127.0.0.1{port}"))

    options["servers"] = (
        numeric_loopback(servers)
        if isinstance(servers, str)
        else [numeric_loopback(server) for server in servers]
    )
    # Keep the availability check inside the NATS client's lifecycle.  A
    # cancelled localhost DNS lookup can leave its executor worker pending and
    # hang pytest's event-loop shutdown when no broker is running.
    options.update(
        allow_reconnect=False,
        connect_timeout=1,
        max_reconnect_attempts=1,
        reconnect_time_wait=0,
    )
    try:
        return await nats.connect(**options)
    except Exception:
        return None


@pytest.mark.asyncio
async def test_nats_to_scoring_end_to_end(tmp_path):
    nc = await _try_connect()
    if nc is None:
        _skip_or_fail(
            "NATS not reachable — start it with "
            f"`docker compose up -d nats` and `bash scripts/create_streams.sh` to run this test"
        )

    js = nc.jetstream()
    suffix = uuid4().hex[:12]
    patient_id = f"P-TEST-{suffix}"
    durable = f"BRAIN_TEST_{suffix}"

    # One full round of vitals, deliberately deteriorating so both Approach A
    # (per-signal) and the composite score should alarm.
    ts = int(time.time() * 1000)
    readings = {
        "heart_rate": 135,
        "spo2": 85,
        "respiratory_rate": 28,
        "blood_pressure": {"systolic": 190, "diastolic": 70},
        "temperature": 39.2,
    }
    for signal_type, value in readings.items():
        payload = vitals_pb2.VitalSign(
            patient_id=patient_id, signal_type=signal_type, timestamp_ms=ts,
            schema_version="1", pipeline_version="test",
        )
        if signal_type == "blood_pressure":
            payload.bp.systolic = value["systolic"]
            payload.bp.diastolic = value["diastolic"]
        else:
            payload.scalar_value = value
        await js.publish(f"vitals.{patient_id}.{signal_type}", payload.SerializeToString())

    try:
        sub = await js.pull_subscribe(f"vitals.{patient_id}.>", durable=durable, stream="VITALS")
        msgs = await sub.fetch(len(readings), timeout=5.0)
        assert len(msgs) == len(readings), f"expected {len(readings)} messages, got {len(msgs)}"

        writer = InfluxWriter(outbox_path=tmp_path / "outbox.sqlite3")
        writer._open_outbox()
        states = {}
        scheduler = BatchScheduler()
        for msg in msgs:
            await _process(
                msg,
                {patient_id: {"condition": "synthetic", "news2_spo2_scale": 1}},
                states,
                scheduler,
                writer,
                js,
            )
        assert writer.pending_count >= len(readings)
        payloads = [
            row[0]
            for row in writer._db.execute("SELECT payload FROM outbox ORDER BY id").fetchall()
        ]
        assert any('"scoring_approach":"A"' in payload for payload in payloads)
        assert any('"scoring_approach":"C"' in payload for payload in payloads)
        writer._db.close()
        writer._db = None
    finally:
        try:
            await js.delete_consumer("VITALS", durable)
        except Exception:
            pass
        await nc.close()


@pytest.mark.asyncio
async def test_invalid_nats_payload_is_dead_lettered_before_scoring():
    nc = await _try_connect()
    if nc is None:
        _skip_or_fail("NATS not reachable for DLQ integration test")
    js = nc.jetstream()
    suffix = uuid4().hex[:12]
    source_subject = f"vitals.P-DLQ-{suffix}.heart_rate"
    durable, dlq_durable = f"BRAIN_TEST_DLQ_{suffix}", f"BRAIN_TEST_DLQ_READER_{suffix}"

    class Writer:
        calls = []

        async def enqueue(self, record):
            self.calls.append(record)

    try:
        await js.publish(source_subject, b"not-a-protobuf-payload")
        sub = await js.pull_subscribe(source_subject, durable=durable, stream="VITALS")
        msg = (await sub.fetch(1, timeout=5))[0]
        dlq_sub = await js.pull_subscribe(
            DLQ_SUBJECT,
            durable=dlq_durable,
            stream="VITALS_DLQ",
            config=ConsumerConfig(
                deliver_policy=DeliverPolicy.NEW,
                ack_policy=AckPolicy.EXPLICIT,
            ),
        )
        writer = Writer()
        await _process(msg, {"P-001": {"condition": "test", "copd_flag": False}}, {}, BatchScheduler(), writer, js)

        dlq = (await dlq_sub.fetch(1, timeout=5))[0]
        envelope = vitals_pb2.DeadLetterEnvelope()
        envelope.ParseFromString(dlq.data)
        assert envelope.original_payload == b"not-a-protobuf-payload"
        assert envelope.source_subject == source_subject
        assert writer.calls == []
        await dlq.ack()
    finally:
        for name in (durable, dlq_durable):
            try:
                stream = "VITALS" if name == durable else "VITALS_DLQ"
                await js.delete_consumer(stream, name)
            except Exception:
                pass
        await nc.close()
