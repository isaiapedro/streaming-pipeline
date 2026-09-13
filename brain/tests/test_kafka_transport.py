"""Broker-free contracts for the isolated Kafka/Schema Registry path."""

from dataclasses import dataclass

import pytest
from confluent_kafka.schema_registry.error import SchemaRegistryError

from brain.validation import ValidationError, ValidVital
from kafka_path.settings import KafkaSettings
from kafka_path.topic_contracts import DLQ_TOPIC, VITALS_TOPIC
from kafka_path.transport import (
    KafkaCodec,
    KafkaPollResult,
    KafkaVitalConsumer,
    KafkaVitalProducer,
)
from schema import vitals_pb2


@dataclass
class FakeMessage:
    payload: bytes
    topic_name: str = "vitals.protobuf.v1"
    key_bytes: bytes = b"P-001"
    partition_id: int = 2
    offset_id: int = 41

    def value(self):
        return self.payload

    def topic(self):
        return self.topic_name

    def key(self):
        return self.key_bytes

    def partition(self):
        return self.partition_id

    def offset(self):
        return self.offset_id

    def error(self):
        return None

    def timestamp(self):
        return (1, 1_700_000_000_000)


class FakeProducer:
    def __init__(self, operations=None, *, fail=False, delivery_error=None):
        self.operations = operations if operations is not None else []
        self.fail = fail
        self.delivery_error = delivery_error
        self.calls = []

    def produce(self, **kwargs):
        self.operations.append("produce")
        if self.fail:
            raise RuntimeError("DLQ unavailable")
        self.calls.append(kwargs)
        kwargs["on_delivery"](self.delivery_error, None)

    def flush(self, timeout):
        self.operations.append("flush")
        return 0


class FakeConsumer:
    def __init__(self, message=None, operations=None):
        self.message = message
        self.operations = operations if operations is not None else []
        self.commits = []
        self.subscriptions = []

    def poll(self, timeout):
        self.operations.append("poll")
        message, self.message = self.message, None
        return message

    def commit(self, **kwargs):
        self.operations.append("commit")
        self.commits.append(kwargs)
        return []

    def subscribe(self, topics):
        self.subscriptions.append(topics)

    def close(self):
        pass


class FakeCodec:
    def __init__(self, *, encoded=b"protobuf", decoded=None, error=None):
        self.encoded = encoded
        self.decoded = decoded
        self.error = error
        self.encoded_vitals = []
        self.encoded_dlqs = []
        self.compatibility_checked = 0

    def assert_compatibility(self):
        self.compatibility_checked += 1

    def encode_vital(self, message):
        self.encoded_vitals.append(message)
        return self.encoded

    def decode_vital(self, payload):
        if self.error is not None:
            raise self.error
        return self.decoded

    def encode_dlq(self, message):
        self.encoded_dlqs.append(message)
        return message.SerializeToString()


class FakeRegistry:
    def __init__(self, compatibility="BACKWARD_TRANSITIVE"):
        self.compatibility = compatibility
        self.set_calls = []

    def set_compatibility(self, *, subject_name, level):
        self.set_calls.append((subject_name, level))

    def get_compatibility(self, *, subject_name):
        return self.compatibility


def _settings():
    return KafkaSettings()


def _vital_message():
    return vitals_pb2.VitalSign(
        patient_id="P-001",
        signal_type="heart_rate",
        scalar_value=82.0,
        timestamp_ms=1_700_000_000_000,
        schema_version="1",
        pipeline_version="test",
    )


def _valid_vital():
    return ValidVital(
        patient_id="P-001",
        signal_type="heart_rate",
        value=82.0,
        timestamp_ms=1_700_000_000_000,
        schema_version="1",
        pipeline_version="test",
        scenario_id="none",
        onset_offset_ms=0,
    )


def test_codec_sets_policy_for_both_value_subjects():
    registry = FakeRegistry()
    codec = KafkaCodec(_settings(), registry=registry)
    codec.set_compatibility()
    assert registry.set_calls == [
        ("vitals.protobuf.v1-value", "BACKWARD_TRANSITIVE"),
        ("vitals.dlq.protobuf.v1-value", "BACKWARD_TRANSITIVE"),
    ]


def test_codec_rejects_wrong_runtime_policy():
    codec = KafkaCodec(_settings(), registry=FakeRegistry("NONE"))
    with pytest.raises(RuntimeError, match="expected BACKWARD_TRANSITIVE"):
        codec.assert_compatibility()


def test_producer_serializes_protobuf_and_uses_patient_partition_key():
    raw_producer = FakeProducer()
    codec = FakeCodec(encoded=b"encoded-vital")
    producer = KafkaVitalProducer(settings=_settings(), producer=raw_producer, codec=codec)
    vital = _vital_message()
    producer.publish(vital)
    assert codec.encoded_vitals == [vital]
    call = raw_producer.calls[0]
    assert call["topic"] == "vitals.protobuf.v1"
    assert call["key"] == b"P-001"
    assert call["value"] == b"encoded-vital"
    assert call["headers"]["schema_version"] == b"1"


def test_valid_record_is_handled_before_synchronous_commit():
    operations = []
    message = FakeMessage(b"encoded-vital")
    raw_consumer = FakeConsumer(operations=operations)
    consumer = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=raw_consumer,
        dlq_producer=FakeProducer(operations), codec=FakeCodec(decoded=_vital_message()),
        pipeline_version="test",
    )

    def handler(vital):
        operations.append("handle")
        assert vital == _valid_vital()

    assert consumer.process_record(message, handler) is True
    assert operations == ["handle", "commit"]
    assert raw_consumer.commits == [{"message": message, "asynchronous": False}]


def test_handler_failure_is_not_dead_lettered_or_committed():
    operations = []
    raw_consumer = FakeConsumer(operations=operations)
    dlq = FakeProducer(operations)
    consumer = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=raw_consumer,
        dlq_producer=dlq, codec=FakeCodec(decoded=_vital_message()),
    )

    def fail_handler(_vital):
        raise RuntimeError("storage unavailable")

    with pytest.raises(RuntimeError, match="storage unavailable"):
        consumer.process_record(FakeMessage(b"encoded-vital"), fail_handler)
    assert operations == []
    assert dlq.calls == []


def test_poll_result_distinguishes_empty_from_rejected_record():
    empty = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=FakeConsumer(),
        dlq_producer=FakeProducer(), codec=FakeCodec(decoded=_vital_message()),
    )
    rejected = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=FakeConsumer(FakeMessage(b"bad")),
        dlq_producer=FakeProducer(), codec=FakeCodec(error=ValidationError("bad")),
    )

    assert empty.poll_result(lambda _vital: None) is KafkaPollResult.EMPTY
    assert rejected.poll_result(lambda _vital: None) is KafkaPollResult.REJECTED


def test_invalid_payload_is_dead_lettered_before_commit():
    operations = []
    message = FakeMessage(b"not-protobuf")
    raw_consumer = FakeConsumer(operations=operations)
    dlq_producer = FakeProducer(operations)
    consumer = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=raw_consumer,
        dlq_producer=dlq_producer,
        codec=FakeCodec(error=ValidationError("malformed_protobuf")),
        pipeline_version="test",
    )
    assert consumer.process_record(message, lambda _vital: pytest.fail("handler called")) is False
    assert operations == ["produce", "flush", "commit"]
    call = dlq_producer.calls[0]
    assert call["topic"] == "vitals.dlq.protobuf.v1"
    envelope = vitals_pb2.DeadLetterEnvelope()
    envelope.ParseFromString(call["value"])
    assert envelope.original_payload == b"not-protobuf"
    assert envelope.source_transport == "kafka"
    assert envelope.source_topic == "vitals.protobuf.v1"
    assert envelope.source_partition == 2
    assert envelope.source_offset == 41
    assert envelope.source_timestamp_ms == 1_700_000_000_000


def test_dlq_failure_does_not_commit_source_offset():
    operations = []
    raw_consumer = FakeConsumer(operations=operations)
    consumer = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=raw_consumer,
        dlq_producer=FakeProducer(operations, fail=True),
        codec=FakeCodec(error=ValidationError("malformed_protobuf")),
    )
    with pytest.raises(RuntimeError, match="DLQ unavailable"):
        consumer.process_record(FakeMessage(b"not-protobuf"), lambda _vital: None)
    assert operations == ["produce"]
    assert raw_consumer.commits == []


def test_registry_outage_is_not_misclassified_as_poison_data():
    raw_consumer = FakeConsumer()
    dlq = FakeProducer()
    consumer = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=raw_consumer,
        dlq_producer=dlq,
        codec=FakeCodec(error=SchemaRegistryError(503, 50001, "registry unavailable")),
    )
    with pytest.raises(SchemaRegistryError):
        consumer.process_record(FakeMessage(b"framed"), lambda _vital: None)
    assert raw_consumer.commits == []
    assert dlq.calls == []


def test_unknown_registry_schema_id_is_dead_lettered_before_commit():
    operations = []
    raw_consumer = FakeConsumer(operations=operations)
    dlq = FakeProducer(operations)
    consumer = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=raw_consumer,
        dlq_producer=dlq,
        codec=FakeCodec(error=SchemaRegistryError(404, 40403, "schema not found")),
    )
    assert consumer.process_record(FakeMessage(b"framed-unknown-schema"), lambda _: None) is False
    assert operations == ["produce", "flush", "commit"]
    assert len(dlq.calls) == 1


def test_kafka_key_must_match_validated_patient():
    raw_consumer = FakeConsumer()
    dlq = FakeProducer()
    consumer = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=raw_consumer,
        dlq_producer=dlq, codec=FakeCodec(decoded=_vital_message()),
    )
    assert consumer.process_record(
        FakeMessage(b"encoded", key_bytes=b"P-999"), lambda _vital: None
    ) is False
    assert len(dlq.calls) == 1
    assert len(raw_consumer.commits) == 1


def test_settings_have_isolated_manual_commit_defaults():
    settings = KafkaSettings()
    assert settings.bootstrap_servers == "localhost:19092"
    assert settings.schema_registry_url == "http://localhost:18081"
    assert settings.vitals_topic == "vitals.protobuf.v1"
    assert settings.dlq_topic == "vitals.dlq.protobuf.v1"
    assert settings.group_id == "brain-kafka-v1"
    assert settings.compatibility == "BACKWARD_TRANSITIVE"
    assert settings.consumer_config() == {
        "bootstrap.servers": "localhost:19092",
        "group.id": "brain-kafka-v1",
        "enable.auto.commit": False,
        "enable.auto.offset.store": False,
        "auto.offset.reset": "earliest",
        "isolation.level": "read_committed",
        "allow.auto.create.topics": False,
    }
    assert settings.producer_config() == {
        "bootstrap.servers": "localhost:19092",
        "enable.idempotence": True,
        "acks": "all",
        "allow.auto.create.topics": False,
    }


def test_kafka_group_id_cannot_be_empty():
    with pytest.raises(ValueError, match="group_id"):
        KafkaSettings(group_id="")


def test_kafka_environment_cannot_bypass_provisioned_topic_contract(monkeypatch):
    monkeypatch.setenv("KAFKA_VITALS_TOPIC", "unmanaged-topic")
    with pytest.raises(ValueError, match="fixed by the provisioned research contract"):
        KafkaSettings.from_env()


def test_kafka_handler_must_finish_synchronously_before_commit():
    operations = []
    raw_consumer = FakeConsumer(operations=operations)
    consumer = KafkaVitalConsumer(
        {"P-001": {}}, _settings(), consumer=raw_consumer,
        dlq_producer=FakeProducer(operations), codec=FakeCodec(decoded=_vital_message()),
    )

    async def asynchronous_handler(_vital):
        return None

    with pytest.raises(TypeError, match="synchronous handler"):
        consumer.process_record(FakeMessage(b"encoded-vital"), asynchronous_handler)
    assert raw_consumer.commits == []


def test_kafka_topic_contracts_accept_expected_descriptions():
    VITALS_TOPIC.assert_describe(
        "Topic: vitals.protobuf.v1 PartitionCount: 3 ReplicationFactor: 1 Configs: "
    )
    DLQ_TOPIC.assert_describe(
        "Topic: vitals.dlq.protobuf.v1 PartitionCount: 1 ReplicationFactor: 1 "
        "Configs: cleanup.policy=compact,delete,retention.ms=86400000"
    )
    DLQ_TOPIC.assert_describe(
        "Topic: vitals.dlq.protobuf.v1 PartitionCount: 1 ReplicationFactor: 1 "
        "Configs: retention.ms=86400000,min.insync.replicas=1, "
        "cleanup.policy=delete,compact"
    )


def test_kafka_topic_contract_rejects_partition_or_config_drift():
    with pytest.raises(RuntimeError, match="partitions must equal 3"):
        VITALS_TOPIC.assert_describe(
            "Topic: vitals.protobuf.v1 PartitionCount: 1 ReplicationFactor: 1 Configs: "
        )
    with pytest.raises(RuntimeError, match="retention.ms must equal 86400000"):
        DLQ_TOPIC.assert_describe(
            "Topic: vitals.dlq.protobuf.v1 PartitionCount: 1 ReplicationFactor: 1 "
            "Configs: cleanup.policy=compact,delete,retention.ms=1234"
        )
