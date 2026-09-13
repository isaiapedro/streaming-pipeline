import ast
import json
import logging
import time
from pathlib import Path

import pytest

from brain.approaches import BatchScheduler
from brain.influx_writer import InfluxWriter, VitalRecord, _safe_error_code
from brain.main import _process as process_nats
from scripts.audit_traceability import REQUIRED_TAGS, _csv_rows, audit_rows
from schema import vitals_pb2

ROOT = Path(__file__).parents[2]


def test_traceability_audit_is_aggregate_and_reports_missing_tags():
    rows = [
        {"_measurement": "patient_vitals", **{tag: "sensitive-tag-value" for tag in REQUIRED_TAGS}},
        {"_measurement": "patient_vitals", **{tag: "sensitive-tag-value" for tag in REQUIRED_TAGS if tag != "threshold_version"}},
        {"_measurement": "alarms", **{tag: "sensitive-tag-value" for tag in REQUIRED_TAGS}},
        {"_measurement": "unrelated", "patient_id": "must-not-appear"},
    ]
    result = audit_rows(rows, "test")
    assert result["records"] == 3
    assert result["status"] == "incomplete"
    assert result["complete_records"] == 2
    assert result["ignored_records"] == 1
    assert result["by_measurement"]["patient_vitals"]["tag_coverage"]["threshold_version"] == {
        "present": 1,
        "pct": 50.0,
    }
    encoded = json.dumps(result)
    assert "must-not-appear" not in encoded
    assert "sensitive-tag-value" not in encoded


def test_traceability_audit_passes_only_when_every_record_is_complete():
    complete = {"_measurement": "alarms", **{tag: "opaque" for tag in REQUIRED_TAGS}}
    assert audit_rows([complete], "test")["status"] == "passed"
    assert audit_rows([], "test")["status"] == "no_records"


def test_traceability_csv_requires_a_measurement_column(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("patient_id,schema_version\nP-001,1\n")
    with pytest.raises(ValueError, match="measurement"):
        _csv_rows(path)


@pytest.mark.asyncio
async def test_outbox_persists_only_a_safe_error_code(tmp_path, caplog):
    class SecretFailure(RuntimeError):
        status_code = 503

    class Api:
        async def write(self, **_kwargs):
            raise SecretFailure("token=do-not-store endpoint=https://private.example")

    class Client:
        def write_api(self):
            return Api()

    writer = InfluxWriter(outbox_path=tmp_path / "outbox.sqlite3")
    writer._open_outbox()
    writer._client = Client()
    record = VitalRecord(
        patient_id="P-SECRET", signal_type="heart_rate", condition="synthetic",
        alarm_level="ok", value=123.456, timestamp_ms=1_800_000_000_000,
        schema_version="1", pipeline_version="test", threshold_version="thresholds",
    )
    with caplog.at_level(logging.ERROR):
        await writer.enqueue(record)
        await writer._flush(force=True)
    stored = writer._db.execute("SELECT last_error FROM outbox").fetchone()[0]
    assert stored == "SecretFailure:status=503"
    assert "token" not in stored and "private.example" not in stored
    assert _safe_error_code(SecretFailure("secret")) == stored
    assert "do-not-store" not in caplog.text
    assert "private.example" not in caplog.text
    assert "P-SECRET" not in caplog.text
    assert "123.456" not in caplog.text
    writer._db.close()


@pytest.mark.asyncio
async def test_rejection_log_does_not_emit_subject_or_patient_identifier(caplog):
    payload = vitals_pb2.VitalSign(
        patient_id="P-SECRET", signal_type="heart_rate", scalar_value=123.456,
        timestamp_ms=int(time.time() * 1000), schema_version="1", pipeline_version="test",
    ).SerializeToString()

    class Message:
        data = payload
        subject = "vitals.P-DIFFERENT.heart_rate"
        async def ack_sync(self):
            return None

    class JetStream:
        async def publish(self, *_args, **_kwargs):
            return None

    class Writer:
        async def enqueue_many(self, _records):
            raise AssertionError("rejected input must not enter storage")

    with caplog.at_level(logging.WARNING):
        await process_nats(Message(), {"P-SECRET": {}}, {}, BatchScheduler(), Writer(), JetStream())
    assert "subject_patient_mismatch" in caplog.text
    assert "P-SECRET" not in caplog.text
    assert "P-DIFFERENT" not in caplog.text
    assert "123.456" not in caplog.text


def test_runtime_log_calls_do_not_pass_identifier_value_or_endpoint_variables():
    forbidden = {
        "patient_id", "subject", "topic", "value", "raw_value", "publish_value",
        "NATS_URL", "INFLUX_URL", "INFLUX_TOKEN", "NATS_PASSWORD",
    }
    violations = []
    for directory in (ROOT / "brain", ROOT / "producer", ROOT / "kafka_path"):
        for path in directory.rglob("*.py"):
            if "tests" in path.parts:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if not isinstance(node.func.value, ast.Name) or node.func.value.id != "log":
                    continue
                names = {child.id for argument in node.args[1:] for child in ast.walk(argument) if isinstance(child, ast.Name)}
                unsafe = names & forbidden
                if unsafe:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{','.join(sorted(unsafe))}")
    assert violations == []
