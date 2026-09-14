"""Live Kafka + Schema Registry integration; optional unless explicitly required."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from urllib.request import urlopen
from uuid import uuid4

import pytest
from confluent_kafka import Consumer, Producer, TopicPartition
from confluent_kafka.admin import AdminClient

from kafka_path.provision import provision
from kafka_path.settings import KafkaSettings
from kafka_path.transport import (
    KafkaCodec,
    KafkaPollResult,
    KafkaVitalConsumer,
    KafkaVitalProducer,
)
from schema import vitals_pb2


def _available(settings: KafkaSettings) -> bool:
    try:
        AdminClient({"bootstrap.servers": settings.bootstrap_servers}).list_topics(timeout=1)
        with urlopen(f"{settings.schema_registry_url}/subjects", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def _skip_or_fail(message: str) -> None:
    if os.getenv("REQUIRE_KAFKA_INTEGRATION", "false").lower() == "true":
        pytest.fail(message)
    pytest.skip(message)


def _poll_until(
    consumer: KafkaVitalConsumer,
    handler,
    expected: KafkaPollResult,
    timeout: float = 10.0,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = consumer.poll_result(handler, timeout=0.5)
        if result is expected:
            return
    pytest.fail("Timed out waiting for the expected Kafka record")


@pytest.mark.integration
def test_kafka_schema_round_trip_and_dlq_ordering():
    base = KafkaSettings.from_env()
    if not _available(base):
        _skip_or_fail("Kafka or Schema Registry is unavailable")

    provision(base, verify_evolution=True)
    suffix = uuid4().hex[:12]
    settings = replace(base, group_id=f"brain-kafka-test-{suffix}")
    codec = KafkaCodec(settings)
    producer = KafkaVitalProducer(settings, codec=codec)
    raw_consumer = Consumer({**settings.consumer_config(), "auto.offset.reset": "latest"})
    consumer = KafkaVitalConsumer(
        {"P-001": {"patient_id": "P-001"}}, settings, codec=codec,
        consumer=raw_consumer,
        pipeline_version="integration-test",
    )
    producer.start()
    consumer.start()
    assignment_deadline = time.monotonic() + 10
    while not raw_consumer.assignment() and time.monotonic() < assignment_deadline:
        raw_consumer.poll(0.1)
    assert raw_consumer.assignment(), "Kafka consumer was not assigned a partition"
    for partition in raw_consumer.assignment():
        _, high = raw_consumer.get_watermark_offsets(partition, timeout=5)
        raw_consumer.seek(TopicPartition(partition.topic, partition.partition, high))

    valid = vitals_pb2.VitalSign(
        patient_id="P-001",
        signal_type="heart_rate",
        scalar_value=82,
        timestamp_ms=int(time.time() * 1000),
        schema_version="1",
        pipeline_version="integration-test",
        scenario_id=f"kafka-{suffix}",
    )
    handled = []
    try:
        producer.publish(valid)
        _poll_until(consumer, handled.append, KafkaPollResult.ACCEPTED)
        assert handled[-1].scenario_id == f"kafka-{suffix}"

        raw_producer = Producer(settings.producer_config())
        valid_wire = codec.encode_vital(valid)
        malformed_wire = f"not-confluent-{suffix}".encode()
        unknown_schema_wire = b"\x00" + (2_147_483_647).to_bytes(4, "big") + b"\x00"
        raw_producer.produce(
            settings.vitals_topic,
            key=b"P-WRONG",
            value=valid_wire,
        )
        raw_producer.produce(settings.vitals_topic, key=b"P-001", value=malformed_wire)
        raw_producer.produce(settings.vitals_topic, key=b"P-001", value=unknown_schema_wire)
        assert raw_producer.flush(10) == 0
        _poll_until(consumer, handled.append, KafkaPollResult.REJECTED)
        _poll_until(consumer, handled.append, KafkaPollResult.REJECTED)
        _poll_until(consumer, handled.append, KafkaPollResult.REJECTED)
    finally:
        consumer.close()

    dlq_consumer = Consumer({
        **settings.consumer_config(),
        "group.id": f"brain-kafka-dlq-test-{suffix}",
    })
    dlq_consumer.subscribe([settings.dlq_topic])
    try:
        deadline = time.monotonic() + 10
        expected_payloads = {valid_wire, malformed_wire, unknown_schema_wire}
        observed_payloads = set()
        while time.monotonic() < deadline and observed_payloads != expected_payloads:
            record = dlq_consumer.poll(0.5)
            if record is None or record.error():
                continue
            envelope = codec.decode_dlq(record.value())
            if envelope.original_payload in expected_payloads:
                assert envelope.source_transport == "kafka"
                assert envelope.source_topic == settings.vitals_topic
                assert envelope.source_partition >= 0
                assert envelope.source_offset >= 0
                observed_payloads.add(envelope.original_payload)
                dlq_consumer.commit(message=record, asynchronous=False)
        assert observed_payloads == expected_payloads
    finally:
        dlq_consumer.close()
