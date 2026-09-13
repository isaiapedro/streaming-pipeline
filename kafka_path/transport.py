"""Kafka producer/consumer using Confluent Protobuf wire framing.

This module is deliberately isolated from the NATS MVP. It reuses the same
canonical generated messages and structural validator, while Kafka-specific
delivery and offset rules stay here.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.error import SerializationError
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.error import SchemaRegistryError
from confluent_kafka.schema_registry.protobuf import ProtobufDeserializer, ProtobufSerializer
from confluent_kafka.serialization import MessageField, SerializationContext

from brain.validation import (
    ValidVital,
    ValidationError,
    dead_letter,
    dead_letter_message_id,
    decode_and_validate,
)
from config.settings import PIPELINE_VERSION
from kafka_path.settings import KafkaSettings
from schema import vitals_pb2


class KafkaDeliveryError(RuntimeError):
    """A Kafka record could not be confirmed before its source was committed."""


class KafkaCodec:
    """Schema Registry framing for canonical vital and dead-letter messages."""

    def __init__(
        self,
        settings: KafkaSettings,
        registry: SchemaRegistryClient | None = None,
        *,
        auto_register: bool = False,
    ) -> None:
        self.settings = settings
        self.registry = registry or SchemaRegistryClient({"url": settings.schema_registry_url})
        serializer_config = {
            "auto.register.schemas": auto_register,
            "normalize.schemas": True,
        }
        self._vital_serializer = ProtobufSerializer(
            vitals_pb2.VitalSign,
            self.registry,
            serializer_config,
        )
        self._vital_deserializer = ProtobufDeserializer(
            vitals_pb2.VitalSign,
            schema_registry_client=self.registry,
        )
        self._dlq_serializer = ProtobufSerializer(
            vitals_pb2.DeadLetterEnvelope,
            self.registry,
            serializer_config,
        )
        self._dlq_deserializer = ProtobufDeserializer(
            vitals_pb2.DeadLetterEnvelope,
            schema_registry_client=self.registry,
        )

    def set_compatibility(self) -> None:
        self.registry.set_compatibility(
            subject_name=self.settings.vitals_subject,
            level=self.settings.compatibility,
        )
        self.registry.set_compatibility(
            subject_name=self.settings.dlq_subject,
            level=self.settings.compatibility,
        )

    def assert_compatibility(self) -> None:
        for subject in (self.settings.vitals_subject, self.settings.dlq_subject):
            actual = self.registry.get_compatibility(subject_name=subject)
            if actual != self.settings.compatibility:
                raise RuntimeError(
                    f"Schema Registry subject {subject} uses {actual}; "
                    f"expected {self.settings.compatibility}"
                )

    def encode_vital(self, message: vitals_pb2.VitalSign) -> bytes:
        encoded = self._vital_serializer(
            message,
            SerializationContext(self.settings.vitals_topic, MessageField.VALUE),
        )
        if encoded is None:
            raise KafkaDeliveryError("Vital serializer returned no payload")
        return encoded

    def decode_vital(self, payload: bytes) -> vitals_pb2.VitalSign:
        decoded = self._vital_deserializer(
            payload,
            SerializationContext(self.settings.vitals_topic, MessageField.VALUE),
        )
        if decoded is None:
            raise ValidationError("empty_kafka_payload")
        return decoded

    def encode_dlq(self, message: vitals_pb2.DeadLetterEnvelope) -> bytes:
        encoded = self._dlq_serializer(
            message,
            SerializationContext(self.settings.dlq_topic, MessageField.VALUE),
        )
        if encoded is None:
            raise KafkaDeliveryError("DLQ serializer returned no payload")
        return encoded

    def decode_dlq(self, payload: bytes) -> vitals_pb2.DeadLetterEnvelope:
        decoded = self._dlq_deserializer(
            payload,
            SerializationContext(self.settings.dlq_topic, MessageField.VALUE),
        )
        if decoded is None:
            raise ValidationError("empty_kafka_dlq_payload")
        return decoded


def _produce_and_wait(
    producer: Any,
    *,
    topic: str,
    value: bytes,
    key: str | bytes,
    headers: Mapping[str, str | bytes] | None = None,
    timeout: float = 10.0,
) -> None:
    errors: list[Exception] = []

    def delivered(error, _message) -> None:
        if error is not None:
            errors.append(KafkaDeliveryError(str(error)))

    producer.produce(
        topic=topic,
        value=value,
        key=key,
        headers=dict(headers or {}),
        on_delivery=delivered,
    )
    remaining = producer.flush(timeout)
    if remaining:
        raise KafkaDeliveryError(f"{remaining} Kafka record(s) were not delivered before timeout")
    if errors:
        raise errors[0]


class KafkaVitalProducer:
    def __init__(
        self,
        settings: KafkaSettings | None = None,
        *,
        codec: KafkaCodec | None = None,
        producer: Any | None = None,
    ) -> None:
        self.settings = settings or KafkaSettings.from_env()
        self.codec = codec or KafkaCodec(self.settings)
        self.producer = producer or Producer(self.settings.producer_config())

    def start(self) -> None:
        self.codec.assert_compatibility()

    def publish(self, message: vitals_pb2.VitalSign, *, timeout: float = 10.0) -> None:
        if not isinstance(message, vitals_pb2.VitalSign):
            raise TypeError("KafkaVitalProducer requires a VitalSign message")
        _produce_and_wait(
            self.producer,
            topic=self.settings.vitals_topic,
            value=self.codec.encode_vital(message),
            key=message.patient_id.encode(),
            headers={
                "schema_version": message.schema_version.encode(),
                "pipeline_version": message.pipeline_version.encode(),
            },
            timeout=timeout,
        )


class KafkaVitalConsumer:
    """Manual-commit consumer with DLQ-before-offset-commit rejection handling."""

    def __init__(
        self,
        profiles: Mapping[str, dict],
        settings: KafkaSettings | None = None,
        *,
        codec: KafkaCodec | None = None,
        consumer: Any | None = None,
        dlq_producer: Any | None = None,
        pipeline_version: str = PIPELINE_VERSION,
    ) -> None:
        self.settings = settings or KafkaSettings.from_env()
        self.codec = codec or KafkaCodec(self.settings)
        self.consumer = consumer or Consumer(self.settings.consumer_config())
        self.dlq_producer = dlq_producer or Producer(self.settings.producer_config())
        self.profiles = dict(profiles)
        self.pipeline_version = pipeline_version

    def start(self) -> None:
        self.codec.assert_compatibility()
        self.consumer.subscribe([self.settings.vitals_topic])

    def poll_once(
        self,
        handler: Callable[[ValidVital], Any],
        *,
        timeout: float = 1.0,
    ) -> bool:
        record = self.consumer.poll(timeout)
        if record is None:
            return False
        if record.error():
            raise KafkaException(record.error())
        return self.process_record(record, handler)

    def process_record(self, record: Any, handler: Callable[[ValidVital], Any]) -> bool:
        if record.topic() != self.settings.vitals_topic:
            raise ValidationError("unexpected_kafka_topic")
        source = f"kafka:{record.topic()}:{record.partition()}:{record.offset()}"
        timestamp = record.timestamp() if hasattr(record, "timestamp") else None
        source_timestamp_ms = timestamp[1] if timestamp and timestamp[1] is not None else 0
        raw = record.value()
        try:
            if raw is None:
                raise ValidationError("empty_kafka_payload")
            decoded = self.codec.decode_vital(raw)
            vital = decode_and_validate(decoded.SerializeToString(), self.profiles)
            record_key = record.key()
            if isinstance(record_key, bytes):
                record_key = record_key.decode(errors="replace")
            if record_key != vital.patient_id:
                raise ValidationError("kafka_key_patient_mismatch")
        except SchemaRegistryError as error:
            if error.http_status_code != 404:
                raise
            self._publish_dlq(raw or b"", source, error, source_timestamp_ms)
            self._commit(record)
            return False
        except (SerializationError, ValidationError, ValueError) as error:
            self._publish_dlq(raw or b"", source, error, source_timestamp_ms)
            self._commit(record)
            return False

        result = handler(vital)
        if inspect.isawaitable(result):
            # A coroutine object has already been created at this point. Close
            # it before rejecting the handler so test and service processes do
            # not leak an un-awaited coroutine warning.
            close = getattr(result, "close", None)
            if close is not None:
                close()
            raise TypeError("KafkaVitalConsumer requires a synchronous handler")
        self._commit(record)
        return True

    def _commit(self, record: Any) -> None:
        partitions = self.consumer.commit(message=record, asynchronous=False)
        for partition in partitions or ():
            if partition.error is not None:
                raise KafkaException(partition.error)

    def _publish_dlq(
        self,
        raw: bytes,
        source: str,
        error: Exception,
        source_timestamp_ms: int,
    ) -> None:
        envelope_bytes = dead_letter(
            raw,
            error,
            source,
            pipeline_version=self.pipeline_version,
            source_transport="kafka",
            source_topic=source.split(":", 3)[1],
            source_partition=int(source.split(":", 3)[2]),
            source_offset=int(source.split(":", 3)[3]),
            source_timestamp_ms=source_timestamp_ms,
        )
        envelope = vitals_pb2.DeadLetterEnvelope()
        envelope.ParseFromString(envelope_bytes)
        message_id = dead_letter_message_id(raw, source)
        _produce_and_wait(
            self.dlq_producer,
            topic=self.settings.dlq_topic,
            value=self.codec.encode_dlq(envelope),
            key=message_id,
            headers={"rejection_id": message_id},
        )

    def close(self) -> None:
        self.consumer.close()
