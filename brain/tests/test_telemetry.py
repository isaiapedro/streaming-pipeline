import json
import time
from pathlib import Path

import pytest

from brain.approaches import BatchScheduler
from brain.config_watcher import watch_thresholds
from brain.influx_writer import (
    AlarmRecord,
    InfluxWriter,
    OutboxFullError,
    VitalRecord,
    _to_point,
)
from brain.local_scorer import make_alarm_event
from brain.main import _process as process_nats
from brain.mqtt_consumer import _process as process_mqtt
from brain.validation import decode_and_validate
from config.thresholds import (
    NEWS2_THRESHOLD_VERSION,
    get_threshold_snapshot,
    install_thresholds,
    threshold_version,
)
from schema import vitals_pb2


def _tags(point) -> str:
    return point.to_line_protocol()


def test_influx_points_include_auditable_metadata_tags():
    vital = VitalRecord(
        patient_id="P-001", signal_type="heart_rate", condition="synthetic",
        alarm_level="ok", value=80, timestamp_ms=1_800_000_000_000,
        schema_version="1", pipeline_version="test-build",
        threshold_version="sha256:thresholds", scenario_id="stable_baseline",
        scoring_approach="A", transport="nats",
    )
    alarm = AlarmRecord(
        patient_id="P-001", condition="synthetic", alarm_level="critical",
        scoring_approach="C", news2_score=8, scenario_id="sepsis_progression",
        timestamp_ms=1_800_000_000_000, schema_version="1",
        pipeline_version="test-build", threshold_version=NEWS2_THRESHOLD_VERSION,
        transport="mqtt", window_complete=True,
    )
    for point in (vital, alarm):
        line = _tags(_to_point(point))
        for expected in (
            "schema_version=1", "pipeline_version=test-build",
            "threshold_version=", "scoring_approach=", "scenario_id=", "transport=",
        ):
            assert expected in line


def _vital_record(timestamp_ms: int = 1_800_000_000_000) -> VitalRecord:
    return VitalRecord(
        patient_id="P-001", signal_type="heart_rate", condition="synthetic",
        alarm_level="ok", value=80, timestamp_ms=timestamp_ms,
        schema_version="1", pipeline_version="test-build",
        threshold_version="sha256:thresholds", scenario_id="stable_baseline",
        scoring_approach="A", transport="nats",
    )


class _WriteApi:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def write(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error


class _InfluxClient:
    def __init__(self, error=None):
        self.api = _WriteApi(error)
        self.closed = False

    def write_api(self):
        return self.api

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_failed_influx_write_is_recovered_from_durable_outbox_after_restart(tmp_path):
    path = tmp_path / "private" / "outbox.sqlite3"
    first = InfluxWriter(outbox_path=path)
    first._open_outbox()
    first._client = _InfluxClient(RuntimeError("offline"))
    await first.enqueue(_vital_record())
    await first.stop()
    assert first._client.closed

    restarted = InfluxWriter(outbox_path=path)
    restarted._open_outbox()
    restarted._client = _InfluxClient()
    assert restarted.pending_count == 1
    await restarted._flush(force=True)
    assert restarted.pending_count == 0
    assert len(restarted._client.api.calls) == 1
    restarted._db.close()
    restarted._db = None


@pytest.mark.asyncio
async def test_outbox_is_idempotent_and_capacity_failure_is_atomic(tmp_path):
    writer = InfluxWriter(outbox_path=tmp_path / "outbox.sqlite3", max_records=1)
    writer._open_outbox()
    record = _vital_record()
    await writer.enqueue_many([record, record])
    assert writer.pending_count == 1

    with pytest.raises(OutboxFullError, match="message remains unacked"):
        await writer.enqueue_many([record, _vital_record(record.timestamp_ms + 1)])
    assert writer.pending_count == 1
    writer._db.close()
    writer._db = None


@pytest.mark.parametrize("field", ["schema_version", "pipeline_version", "threshold_version"])
def test_missing_version_metadata_is_rejected(field):
    values = dict(
        patient_id="P-001", signal_type="heart_rate", condition="synthetic",
        alarm_level="ok", value=80, timestamp_ms=1_800_000_000_000,
        schema_version="1", pipeline_version="test", threshold_version="thresholds-v1",
    )
    values[field] = ""
    with pytest.raises(ValueError, match=field):
        VitalRecord(**values)


def test_threshold_snapshot_update_is_atomic_and_content_addressed():
    original = get_threshold_snapshot()
    replacement = {name: dict(bands) for name, bands in original.values.items()}
    replacement["heart_rate"]["warning_high"] = 101
    expected_version = threshold_version(replacement)
    try:
        installed = install_thresholds(replacement, expected_version)
        assert installed.version == expected_version
        assert original.values["heart_rate"]["warning_high"] == 100
        with pytest.raises(TypeError):
            installed.values["heart_rate"]["warning_high"] = 102

        before_rejection = get_threshold_snapshot()
        with pytest.raises(ValueError, match="does not match"):
            install_thresholds(replacement, "wrong-version")
        assert get_threshold_snapshot() is before_rejection
    finally:
        install_thresholds(original.values, original.version)


@pytest.mark.asyncio
async def test_hot_reload_callback_observes_one_atomic_snapshot():
    original = get_threshold_snapshot()
    replacement = {name: dict(bands) for name, bands in original.values.items()}
    replacement["spo2"]["warning_low"] = 93
    version = threshold_version(replacement)

    class Entry:
        value = json.dumps({**replacement, "_threshold_version": version}).encode()
        operation = "PUT"
        revision = 7

    class KV:
        async def watch(self, _key):
            async def entries():
                yield Entry()
            return entries()

    class JS:
        async def key_value(self, _bucket):
            return KV()

    observed = []
    try:
        await watch_thresholds(JS(), lambda snapshot, latency: observed.append((snapshot, latency)))
        assert len(observed) == 1
        snapshot, latency = observed[0]
        assert snapshot is get_threshold_snapshot()
        assert snapshot.version == version
        assert snapshot.values["spo2"]["warning_low"] == 93
        assert latency is None
    finally:
        install_thresholds(original.values, original.version)


class _Writer:
    def __init__(self):
        self.records = []

    async def enqueue(self, record):
        self.records.append(record)


class _AtomicWriter(_Writer):
    def __init__(self, error=None):
        super().__init__()
        self.error = error
        self.transactions = 0

    async def enqueue_many(self, records):
        self.transactions += 1
        if self.error:
            raise self.error
        self.records.extend(records)


class _Message:
    def __init__(self, data):
        self.data = data
        self.subject = "vitals.P-001.heart_rate"
        self.acked = False

    async def ack_sync(self):
        self.acked = True


class _JetStream:
    async def publish(self, *_args, **_kwargs):
        raise AssertionError("valid payload must not use the DLQ")


def _payload():
    return vitals_pb2.VitalSign(
        patient_id="P-001", signal_type="heart_rate", scalar_value=80,
        timestamp_ms=int(time.time() * 1000), schema_version="1",
        pipeline_version="producer-test", scenario_id="stable_baseline",
    ).SerializeToString()


@pytest.mark.asyncio
async def test_nats_and_mqtt_preserve_validated_metadata_with_transport_parity():
    profiles = {"P-001": {"condition": "synthetic", "copd_flag": False}}
    nats_writer, mqtt_writer = _Writer(), _Writer()
    message = _Message(_payload())
    await process_nats(message, profiles, {}, BatchScheduler(), nats_writer, _JetStream())
    await process_mqtt(_payload(), profiles, {}, BatchScheduler(), mqtt_writer,
                       source_subject="vitals.P-001.heart_rate")

    nats_record, mqtt_record = nats_writer.records[0], mqtt_writer.records[0]
    assert message.acked
    assert nats_record.schema_version == mqtt_record.schema_version == "1"
    assert nats_record.pipeline_version == mqtt_record.pipeline_version == "producer-test"
    assert nats_record.threshold_version == mqtt_record.threshold_version
    assert (nats_record.transport, mqtt_record.transport) == ("nats", "mqtt")


@pytest.mark.asyncio
async def test_nats_ack_follows_one_atomic_durable_handoff():
    profiles = {"P-001": {"condition": "synthetic", "news2_spo2_scale": 1}}
    message = _Message(_payload())
    writer = _AtomicWriter()
    await process_nats(message, profiles, {}, BatchScheduler(), writer, _JetStream())
    assert writer.transactions == 1
    assert writer.records
    assert message.acked

    failed_message = _Message(_payload())
    failed_writer = _AtomicWriter(OutboxFullError("full"))
    failed_states = {}
    failed_scheduler = BatchScheduler()
    with pytest.raises(OutboxFullError, match="full"):
        await process_nats(
            failed_message, profiles, failed_states, failed_scheduler, failed_writer, _JetStream()
        )
    assert failed_writer.transactions == 1
    assert not failed_message.acked
    assert failed_states == {}
    assert failed_scheduler._last_tick == {}


def test_local_alarm_preserves_validated_versions_and_adds_audit_headers():
    raw = _payload()
    vital = decode_and_validate(
        raw, {"P-001": {"patient_id": "P-001"}},
        source_subject="vitals.P-001.heart_rate",
    )
    event, headers = make_alarm_event(vital, "high", 8)
    assert event.schema_version == vital.schema_version
    assert event.pipeline_version == vital.pipeline_version
    assert headers == {
        "X-Scoring-Approach": "C",
        "X-Scenario-Id": "stable_baseline",
        "X-Threshold-Version": NEWS2_THRESHOLD_VERSION,
    }


def test_grafana_assets_have_filters_versions_and_safe_alert(tmp_path):
    root = Path(__file__).parents[2]
    dashboard = json.loads((root / "grafana/provisioning/dashboards/comparison.json").read_text())
    assert {item["name"] for item in dashboard["templating"]["list"]} >= {
        "patient", "scenario", "approach"
    }
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {
        "NEWS2 score — Approaches B/C only",
        "Alarm timing by approach",
        "Alarming observations per minute by approach",
        "Telemetry versions",
    } <= titles
    queries = [target.get("query", "") for panel in dashboard["panels"] for target in panel.get("targets", [])]
    all_queries = "\n".join(queries)
    assert all("v.timeRangeStart" in query and "v.timeRangeStop" in query for query in queries)
    assert all("${patient:regex}" in query and "${scenario:regex}" in query and "${approach:regex}" in query for query in queries)
    assert "schema_version" in all_queries
    assert "threshold_version" in all_queries
    timing = next(panel for panel in dashboard["panels"] if panel["title"] == "Alarm timing by approach")
    volume = next(panel for panel in dashboard["panels"] if panel["title"].startswith("Alarming observations"))
    for panel in (timing, volume):
        query = panel["targets"][0]["query"]
        assert 'r._measurement == "patient_vitals"' in query
        assert 'r.scoring_approach == "A"' in query
        assert "union(tables: [a, bc])" in query
    rules = (root / "grafana/provisioning/alerting/rules.yml").read_text()
    assert "isPaused: true" in rules
    assert "INFLUX_TOKEN" not in rules
    assert "data_class: synthetic" in rules
    assert 'r.scenario_id != "none"' in rules
    datasource = (root / "grafana/provisioning/datasources/influxdb.yml").read_text()
    assert "uid: influxdb-cloud" in datasource
    assert "${INFLUX_URL}" in datasource and "${INFLUX_TOKEN}" in datasource
    assert "tlsSkipVerify: false" in datasource
    assert "http://" not in datasource and "https://" not in datasource
